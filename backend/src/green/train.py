"""Train the natural-cover NDVI model and report honest scores (docs/research §5–6)."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from green.crops import near_farm
from green.grid import spatial_blocks
from green.ndvi import quality_weight
from green.sources import CLIMATE_LAYERS, COVER_CLASSES, SOIL_LAYERS
from green.store import Store

logger = logging.getLogger(__name__)

# Mean rainfall over the RECENT_MONTHS before each month: soil and plants lag the weather.
RECENT_MONTHS = 3
INPUT_LAYERS = (*SOIL_LAYERS, *CLIMATE_LAYERS, "recent_prcp", "month_sin", "month_cos")
# A cell trains the model only when natural cover fills most of it (docs/research §4).
NATURAL_SHARE = 0.75
HELD_OUT_YEARS = 3
# Unseen places (spatial blocks), unseen years, and both at once.
HOLDOUTS = ("spatial", "temporal", "combined")


def input_stack(
    soil: dict[str, np.ndarray],
    climate: dict[str, np.ndarray],
    last_year: dict[str, np.ndarray] | None,
) -> np.ndarray:
    """(12, height, width, layer) Input layers for one year, in INPUT_LAYERS order.

    `last_year` is the previous year's climate, for recent rainfall early in the year; without
    it, those months' recent rainfall is NaN.
    """
    months, height, width = climate[CLIMATE_LAYERS[0]].shape
    angle = 2 * np.pi * np.arange(months) / 12
    columns = [np.broadcast_to(soil[name], (months, height, width)) for name in SOIL_LAYERS]
    columns += [climate[name] for name in CLIMATE_LAYERS]
    columns.append(_recent_prcp(climate, last_year))
    columns += [
        np.broadcast_to(f(angle)[:, None, None], (months, height, width)) for f in (np.sin, np.cos)
    ]
    return np.stack(columns, axis=-1)


def _recent_prcp(
    climate: dict[str, np.ndarray], last_year: dict[str, np.ndarray] | None
) -> np.ndarray:
    prcp = climate["climate_prcp"]
    before = (
        last_year["climate_prcp"][-RECENT_MONTHS:]
        if last_year is not None
        else np.full((RECENT_MONTHS, *prcp.shape[1:]), np.nan)
    )
    window = np.lib.stride_tricks.sliding_window_view(
        np.concatenate([before, prcp]), RECENT_MONTHS, axis=0
    )
    return window[:-1].mean(axis=-1)


def last_year_climate(store: Store, year: int) -> dict[str, np.ndarray] | None:
    """The climate for the year before `year`, if it has been extracted."""
    return store.load(f"climate/{year - 1}") if year - 1 in store.years("climate") else None


def natural_cells(store: Store) -> np.ndarray:
    return store.load("land_cover")["natural_share"] >= NATURAL_SHARE


def run_size(
    natural_share: np.ndarray, farm: np.ndarray, blocks: np.ndarray, years: list[int]
) -> dict:
    """The counts issue #15 uses to judge whether a run is big enough to trust its scores."""
    natural = natural_share >= NATURAL_SHARE
    per_block = np.unique(blocks[natural], return_counts=True)[1]
    near_per_block = np.unique(blocks[near_farm(farm, natural)], return_counts=True)[1]
    return {
        "natural_cells": int(natural.sum()),
        "blocks_with_50_natural_cells": int((per_block >= 50).sum()),
        "blocks_with_25_natural_cells_next_to_farm": int((near_per_block >= 25).sum()),
        "years": years,
    }


@dataclass
class Rows:
    x: np.ndarray
    y: np.ndarray
    weight: np.ndarray
    year: np.ndarray
    month: np.ndarray
    row: np.ndarray
    col: np.ndarray

    def take(self, keep: np.ndarray) -> Rows:
        return Rows(*(getattr(self, f)[keep] for f in self.__dataclass_fields__))


def build_rows(store: Store) -> Rows:
    """One row per natural cell, year and month that has Observed NDVI and every Input layer."""
    soil = store.load("soil")
    natural = natural_cells(store)
    parts = []
    for year in store.years("ndvi"):
        observed = store.load(f"ndvi/{year}")
        x = input_stack(soil, store.load(f"climate/{year}"), last_year_climate(store, year))
        y = observed["ndvi"]
        keep = natural & ~np.isnan(y) & ~np.isnan(x).any(axis=-1)
        month, row, col = np.nonzero(keep)
        parts.append(
            Rows(
                x[keep],
                y[keep],
                quality_weight(np.nan_to_num(observed["good_share"][keep])),
                np.full(len(month), year),
                month,
                row,
                col,
            )
        )
    return Rows(
        *(np.concatenate([getattr(p, f) for p in parts]) for f in Rows.__dataclass_fields__)
    )


def assign_folds(blocks: np.ndarray, n_folds: int, seed: int) -> np.ndarray:
    """Fold of each item, with all items of one block in the same fold."""
    unique = np.unique(blocks)
    order = np.random.default_rng(seed).permutation(len(unique))
    fold_of_block = dict(zip(unique, order % min(n_folds, len(unique)), strict=True))
    return np.array([fold_of_block[b] for b in blocks])


def held_out_years(years: list[int], n: int = HELD_OUT_YEARS) -> list[int]:
    """The last n years, kept for the temporal test; at least one year is left to train on."""
    n = min(n, max(len(years) // 4, 1))
    return sorted(years)[-n:]


def _r2(error: np.ndarray, total: float) -> float:
    return float(1 - (error**2).sum() / total) if total else float("nan")


def metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - observed
    total = ((observed - observed.mean()) ** 2).sum()
    return {
        "rmse": float(np.sqrt((error**2).mean())),
        "mae": float(np.abs(error).mean()),
        "r2": _r2(error, total),
    }


def gbm(seed: int) -> Pipeline:
    return Pipeline(
        [("scale", StandardScaler()), ("model", HistGradientBoostingRegressor(random_state=seed))]
    )


def _fit(model: Pipeline, rows: Rows) -> Pipeline:
    return model.fit(rows.x, rows.y, model__sample_weight=rows.weight)


def _predict_all(train: Rows, test: Rows, seed: int, climatology: bool) -> dict[str, np.ndarray]:
    """Predictions on `test` from each baseline and the model, all fitted on `train` only."""
    predictions = {
        "mean": np.full(len(test.y), np.average(train.y, weights=train.weight)),
        "ridge": _fit(Pipeline([("scale", StandardScaler()), ("model", Ridge())]), train).predict(
            test.x
        ),
        "gbm": _fit(gbm(seed), train).predict(test.x),
    }
    if climatology:
        # Only fair for unseen years: unseen places have no history.
        test_climatology = _climatology(train, test, fallback=predictions["mean"])
        predictions["climatology"] = test_climatology
        # Do the Input layers explain the Departure?
        departure = _training_departures(train)
        has_departure = ~np.isnan(departure)
        departure_rows = Rows(**{**vars(train), "y": departure}).take(has_departure)
        predictions["climatology_gbm"] = test_climatology + _fit(gbm(seed), departure_rows).predict(
            test.x
        )
    return predictions


def _climatology(train: Rows, test: Rows, fallback: np.ndarray | float) -> np.ndarray:
    """Mean `train` NDVI for each `test` row's cell and month, or `fallback` where it has none."""
    dims = (
        max(train.row.max(), test.row.max()) + 1,
        max(train.col.max(), test.col.max()) + 1,
        12,
    )
    train_key = np.ravel_multi_index((train.row, train.col, train.month), dims)
    test_key = np.ravel_multi_index((test.row, test.col, test.month), dims)
    order = np.argsort(train_key)
    unique, start = np.unique(train_key[order], return_index=True)
    means = np.add.reduceat(train.y[order], start) / np.diff(np.append(start, len(order)))
    index = np.clip(np.searchsorted(unique, test_key), 0, len(unique) - 1)
    return np.where(unique[index] == test_key, means[index], fallback)


def _training_departures(train: Rows) -> np.ndarray:
    """Each row's Observed NDVI minus the mean for its cell and month over the other training years.

    Leaving the row's own year out keeps it from pulling its climatology toward itself, which
    would shrink the Departures. NaN where no other year has that cell and month.
    """
    cell_month = _group(train.row, train.col, train.month)
    own_year = _group(train.row, train.col, train.month, train.year)
    others_sum = (
        np.bincount(cell_month, train.y)[cell_month] - np.bincount(own_year, train.y)[own_year]
    )
    others_count = np.bincount(cell_month)[cell_month] - np.bincount(own_year)[own_year]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(others_count > 0, train.y - others_sum / others_count, np.nan)


def _group(*keys: np.ndarray) -> np.ndarray:
    """A group index for each row, shared by rows with equal `keys`."""
    return np.unique(np.stack(keys), axis=1, return_inverse=True)[1].ravel()


def _departure_r2(observed: np.ndarray, predicted: np.ndarray, usual: np.ndarray) -> float:
    """R² of the Departure from `usual`; 0 for predicting no Departure, 1 for a perfect one."""
    return _r2(predicted - observed, ((observed - usual) ** 2).sum())


def _summarise(per_fold: list[dict[str, dict[str, float]]]) -> dict:
    return {
        model: {
            name: {
                "mean": float(np.mean([f[model][name] for f in per_fold])),
                "std": float(np.std([f[model][name] for f in per_fold])),
            }
            for name in ("rmse", "mae", "r2")
        }
        for model in per_fold[0]
    }


def evaluate(
    rows: Rows, folds: np.ndarray, test_years: list[int], seed: int
) -> tuple[dict, Rows, np.ndarray, np.ndarray]:
    """Scores for spatial-only, temporal-only and combined holdouts.

    Also returns every held-out row, its model prediction and its holdout (one of
    HOLDOUTS), for the error on natural cells next to farm land (ADR 0006). A row of a
    held-out year appears twice: once unseen in time only, once unseen in both.
    """
    is_test_year = np.isin(rows.year, test_years)
    report: dict = {"test_years": test_years, "folds": int(folds.max()) + 1}

    logger.info("Fitting unseen-years holdout (test years %s)", test_years)
    temporal = _predict_all(rows.take(~is_test_year), rows.take(is_test_year), seed, True)
    test = rows.take(is_test_year)
    report["temporal"] = _summarise([{m: metrics(test.y, p) for m, p in temporal.items()}])
    report["temporal_departure_r2"] = {
        m: _departure_r2(test.y, p, temporal["climatology"]) for m, p in temporal.items()
    }
    held_out = [(test, temporal["gbm"], "temporal")]

    past = rows.take(~is_test_year)
    past_folds = folds[~is_test_year]
    if report["folds"] < 2:
        logger.warning("Only one spatial block: skipping spatial and combined holdouts")
        return report, *_held_out_rows(held_out)

    spatial, combined = [], []
    for k in range(report["folds"]):
        logger.info("Fitting spatial fold %d of %d", k + 1, report["folds"])
        held = past.take(past_folds == k)
        predictions = _predict_all(past.take(past_folds != k), held, seed, False)
        held_out.append((held, predictions["gbm"], "spatial"))
        spatial.append({m: metrics(held.y, p) for m, p in predictions.items()})

        unseen = test.take(folds[is_test_year] == k)
        if len(unseen.y):
            predictions = _predict_all(past.take(past_folds != k), unseen, seed, False)
            held_out.append((unseen, predictions["gbm"], "combined"))
            combined.append({m: metrics(unseen.y, p) for m, p in predictions.items()})
    report["spatial"] = _summarise(spatial)
    if combined:
        report["combined"] = _summarise(combined)
    return report, *_held_out_rows(held_out)


def _held_out_rows(
    parts: list[tuple[Rows, np.ndarray, str]],
) -> tuple[Rows, np.ndarray, np.ndarray]:
    rows = Rows(
        *(np.concatenate([getattr(r, f) for r, _, _ in parts]) for f in Rows.__dataclass_fields__)
    )
    predicted = np.concatenate([p for _, p, _ in parts])
    holdout = np.concatenate([np.full(len(p), name) for _, p, name in parts])
    return rows, predicted, holdout


def train(
    store: Store, model_path: Path, block_km: float = 200, n_folds: int = 5, seed: int = 0
) -> dict:
    """Evaluate, then fit the final model on every row and save it with its scaler and metadata."""
    rows = build_rows(store)
    if not len(rows.y):
        raise ValueError(
            f"no natural cells (natural cover ≥ {NATURAL_SHARE:.0%}) with Observed NDVI to train on"
        )
    years = sorted(set(rows.year.tolist()))
    blocks = spatial_blocks(store.grid(), block_km)
    cell_folds = assign_folds(blocks.ravel(), n_folds, seed).reshape(blocks.shape)
    folds = cell_folds[rows.row, rows.col]
    test_years = held_out_years(years)

    logger.info("Evaluating on %d rows from %d years", len(rows.y), len(years))
    report, held_out, predicted, holdout = evaluate(rows, folds, test_years, seed)
    land_cover = store.load("land_cover")
    farm = land_cover["cover_class"] == COVER_CLASSES.index("farm")
    report["run_size"] = run_size(land_cover["natural_share"], farm, blocks, years)
    store.save(
        "train/held_out",
        year=held_out.year,
        month=held_out.month,
        row=held_out.row,
        col=held_out.col,
        observed=held_out.y,
        predicted=predicted,
        holdout=holdout,
    )
    store.save("train/blocks", blocks=blocks, folds=cell_folds)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Fitting final model on all %d rows", len(rows.y))
    joblib.dump(
        {
            # The pipeline holds the fitted scaler and model together.
            "pipeline": _fit(gbm(seed), rows),
            "input_layers": INPUT_LAYERS,
            "metadata": {
                "trained_at": datetime.now(UTC).isoformat(),
                "years": years,
                "rows": len(rows.y),
                "block_km": block_km,
                "n_folds": n_folds,
                "seed": seed,
                "natural_share": NATURAL_SHARE,
                "grid": store.grid().to_dict(),
            },
            "metrics": report,
        },
        model_path,
    )
    return report
