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

from green.grid import spatial_blocks
from green.ndvi import quality_weight
from green.sources import CLIMATE_LAYERS, SOIL_LAYERS
from green.store import Store

logger = logging.getLogger(__name__)

INPUT_LAYERS = (*SOIL_LAYERS, *CLIMATE_LAYERS, "month_sin", "month_cos")
# A cell trains the model only when natural cover fills most of it (docs/research §4).
NATURAL_SHARE = 0.75
HELD_OUT_YEARS = 3


def input_stack(soil: dict[str, np.ndarray], climate: dict[str, np.ndarray]) -> np.ndarray:
    """(12, height, width, layer) Input layers for one year, in INPUT_LAYERS order."""
    months, height, width = climate[CLIMATE_LAYERS[0]].shape
    angle = 2 * np.pi * np.arange(months) / 12
    columns = [np.broadcast_to(soil[name], (months, height, width)) for name in SOIL_LAYERS]
    columns += [climate[name] for name in CLIMATE_LAYERS]
    columns += [
        np.broadcast_to(f(angle)[:, None, None], (months, height, width)) for f in (np.sin, np.cos)
    ]
    return np.stack(columns, axis=-1)


def natural_cells(store: Store) -> np.ndarray:
    return store.load("land_cover")["natural_share"] >= NATURAL_SHARE


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
        x = input_stack(soil, store.load(f"climate/{year}"))
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


def metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - observed
    total = ((observed - observed.mean()) ** 2).sum()
    return {
        "rmse": float(np.sqrt((error**2).mean())),
        "mae": float(np.abs(error).mean()),
        "r2": float(1 - (error**2).sum() / total) if total else float("nan"),
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
        # Per-cell, per-month mean from training years; only fair for unseen years.
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
        known = unique[index] == test_key
        predictions["climatology"] = np.where(known, means[index], predictions["mean"])
    return predictions


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
) -> tuple[dict, Rows, np.ndarray]:
    """Scores for spatial-only, temporal-only and combined holdouts.

    Also returns the spatial out-of-fold rows and their model predictions, for the
    error on natural cells next to farm land (ADR 0006).
    """
    is_test_year = np.isin(rows.year, test_years)
    report: dict = {"test_years": test_years, "folds": int(folds.max()) + 1}

    temporal = _predict_all(rows.take(~is_test_year), rows.take(is_test_year), seed, True)
    test = rows.take(is_test_year)
    report["temporal"] = _summarise([{m: metrics(test.y, p) for m, p in temporal.items()}])

    past = rows.take(~is_test_year)
    past_folds = folds[~is_test_year]
    if report["folds"] < 2:
        logger.warning("Only one spatial block: skipping spatial and combined holdouts")
        return report, past.take(np.zeros(len(past.y), bool)), np.array([])

    spatial, combined = [], []
    oof = np.full(len(past.y), np.nan)
    for k in range(report["folds"]):
        held = past.take(past_folds == k)
        predictions = _predict_all(past.take(past_folds != k), held, seed, False)
        oof[past_folds == k] = predictions["gbm"]
        spatial.append({m: metrics(held.y, p) for m, p in predictions.items()})

        unseen = test.take(folds[is_test_year] == k)
        if len(unseen.y):
            predictions = _predict_all(past.take(past_folds != k), unseen, seed, False)
            combined.append({m: metrics(unseen.y, p) for m, p in predictions.items()})
    report["spatial"] = _summarise(spatial)
    if combined:
        report["combined"] = _summarise(combined)
    return report, past, oof


def train(
    store: Store, model_path: Path, block_km: float = 200, n_folds: int = 5, seed: int = 0
) -> dict:
    """Evaluate, then fit the final model on every row and save it with its scaler and metadata."""
    rows = build_rows(store)
    years = sorted(set(rows.year.tolist()))
    blocks = spatial_blocks(store.grid(), block_km)
    cell_folds = assign_folds(blocks.ravel(), n_folds, seed).reshape(blocks.shape)
    folds = cell_folds[rows.row, rows.col]
    test_years = held_out_years(years)

    logger.info("Evaluating on %d rows from %d years", len(rows.y), len(years))
    report, oof_rows, oof = evaluate(rows, folds, test_years, seed)
    store.save(
        "train/oof",
        year=oof_rows.year,
        month=oof_rows.month,
        row=oof_rows.row,
        col=oof_rows.col,
        observed=oof_rows.y,
        predicted=oof,
    )
    store.save("train/blocks", blocks=blocks, folds=cell_folds)

    model_path.parent.mkdir(parents=True, exist_ok=True)
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
