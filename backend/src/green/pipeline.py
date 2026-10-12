"""The pipeline steps: extract → train → predict → crop effect → tiles → publish."""

import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import joblib
import numpy as np

from green.crops import (
    FIRST_CDL_YEAR,
    crop_effect,
    dominant_group,
    near_farm,
    regional_map,
    regional_rmse,
    worst_error,
)
from green.layers import LayerDefinition, load_layers
from green.ndvi import FIRST_VIIRS_YEAR, apply_correction, fit_correction
from green.sources import CLIMATE_LAYERS, SOIL_LAYERS, Source
from green.store import Store
from green.tiles import MAX_ZOOM, write_pmtiles
from green.train import HOLDOUTS, input_stack, natural_cells, train

logger = logging.getLogger(__name__)

# Terra stops collecting science data in about early 2027 (ADR 0005).
LAST_MODIS_YEAR = 2026
# Every year both satellites have data; the VIIRS correction is always fitted on all of them.
OVERLAP_YEARS = list(range(FIRST_VIIRS_YEAR, LAST_MODIS_YEAR + 1))
# A cell counts as farm land, for the error next to farm land, when crops cover half of it.
FARM_SHARE = 0.5


def ndvi_correction(source: Source, store: Store, cover_class: np.ndarray) -> np.ndarray:
    """The VIIRS-to-MODIS correction, fitted once per region on every overlap year (ADR 0005).

    It never depends on the years a run covers, so every run gives the same Observed NDVI
    for a place and month. A saved correction is reused only if it was fitted on the same
    years from the same source; otherwise, say after a synthetic run, it is fitted again.
    """
    if store.path("ndvi_correction").exists():
        saved = store.load("ndvi_correction")
        if (
            "years" in saved
            and list(saved["years"]) == OVERLAP_YEARS
            and "source" in saved
            and str(saved["source"]) == source.name
        ):
            return saved["coeffs"]
    grid = store.grid()
    logger.info("Fitting VIIRS correction on %d–%d", OVERLAP_YEARS[0], OVERLAP_YEARS[-1])
    modis = np.stack([source.ndvi(grid, y, "modis")[0] for y in OVERLAP_YEARS])
    viirs = np.stack([source.ndvi(grid, y, "viirs")[0] for y in OVERLAP_YEARS])
    coeffs = fit_correction(modis, viirs, cover_class)
    store.save(
        "ndvi_correction",
        coeffs=coeffs,
        years=np.array(OVERLAP_YEARS),
        source=np.array(source.name),
    )
    return coeffs


def extract(source: Source, store: Store, years: list[int]) -> None:
    """Fetch soil once, then climate, Observed NDVI and crop shares per year."""
    grid = store.grid()
    logger.info("Extracting soil and land cover")
    store.save("soil", **source.soil(grid))
    natural_share, cover_class = source.land_cover(grid)
    store.save("land_cover", natural_share=natural_share, cover_class=cover_class)

    if any(y >= FIRST_VIIRS_YEAR for y in years):
        coeffs = ndvi_correction(source, store, cover_class)

    for year in years:
        logger.info("Extracting %d", year)
        store.save(f"climate/{year}", **source.climate(grid, year))
        if year < FIRST_VIIRS_YEAR:
            ndvi, good = source.ndvi(grid, year, "modis")
        else:
            ndvi, good = source.ndvi(grid, year, "viirs")
            ndvi = apply_correction(ndvi, cover_class, coeffs)
        store.save(f"ndvi/{year}", ndvi=ndvi, good_share=good)
        if year >= FIRST_CDL_YEAR:
            store.save(f"crops/{year}", shares=source.crop_shares(grid, year))


def predict(store: Store, model_path: Path) -> None:
    """Predicted NDVI over every cell, and the residual on natural cells, per year."""
    model = joblib.load(model_path)
    soil = store.load("soil")
    natural = natural_cells(store)
    for year in store.years("climate"):
        x = input_stack(soil, store.load(f"climate/{year}"))
        valid = ~np.isnan(x).any(axis=-1)
        predicted = np.full(valid.shape, np.nan)
        predicted[valid] = model["pipeline"].predict(x[valid])
        observed = store.load(f"ndvi/{year}")["ndvi"]
        residual = np.where(natural, observed - predicted, np.nan)
        store.save(f"predict/{year}", predicted=predicted, residual=residual)


def crop_effects(store: Store) -> dict:
    """Crop type and Crop effect per year, and the model error next to farm land per region.

    The error is given for unseen places, unseen years and both (HOLDOUTS).
    """
    natural = natural_cells(store)
    for year in store.years("crops"):
        shares = store.load(f"crops/{year}")["shares"]
        groups = dominant_group(shares)
        observed = store.load(f"ndvi/{year}")["ndvi"]
        predicted = store.load(f"predict/{year}")["predicted"]
        effect = crop_effect(observed, predicted, groups)
        farm = shares.sum(axis=0) >= FARM_SHARE
        store.save(f"crop_effect/{year}", groups=groups, effect=effect, farm=farm)

    # Held-out predictions keep this honest: each cell was predicted by a model that never
    # saw its spatial block, its year, or both (ADR 0006).
    held_out = store.load("train/held_out")
    blocks = store.load("train/blocks")["blocks"]
    near = np.zeros(natural.shape, bool)
    for year in store.years("crop_effect"):
        near |= near_farm(store.load(f"crop_effect/{year}")["farm"], natural)
    rows, cols = held_out["row"], held_out["col"]
    errors = {}
    for holdout in HOLDOUTS:
        keep = held_out["holdout"] == holdout
        errors[holdout] = regional_rmse(
            held_out["observed"][keep],
            held_out["predicted"][keep],
            near[rows, cols][keep],
            blocks[rows, cols][keep],
        )
    (store.root / "crop_effect").mkdir(parents=True, exist_ok=True)
    (store.root / "crop_effect" / "regional_error.json").write_text(json.dumps(errors, indent=2))
    return errors


def _layer_maps(store: Store, layer_id: str) -> Iterator[tuple[str, np.ndarray]]:
    """Every (name, 2D array) map for a layer: one map, or one per year or month."""

    def monthly(kind: str, key: str):
        for year in store.years(kind):
            values = store.load(f"{kind}/{year}")[key]
            for month in range(12):
                yield f"{year}-{month + 1:02d}", values[month]

    if layer_id in SOIL_LAYERS:
        yield layer_id, store.load("soil")[layer_id]
    elif layer_id in CLIMATE_LAYERS:
        yield from monthly("climate", layer_id)
    elif layer_id == "observed_ndvi":
        yield from monthly("ndvi", "ndvi")
    elif layer_id == "predicted_ndvi":
        yield from monthly("predict", "predicted")
    elif layer_id == "ndvi_residual":
        yield from monthly("predict", "residual")
    elif layer_id == "crop_effect":
        yield from monthly("crop_effect", "effect")
    elif layer_id == "crop_effect_error":
        # The map shows the largest error of the three holdouts, so it is never too low.
        errors = json.loads((store.root / "crop_effect" / "regional_error.json").read_text())
        by_holdout = {h: {int(b): e for b, e in by_block.items()} for h, by_block in errors.items()}
        blocks = store.load("train/blocks")["blocks"]
        yield layer_id, regional_map(worst_error(by_holdout), blocks)
    elif layer_id == "crop_type":
        for year in store.years("crop_effect"):
            groups = store.load(f"crop_effect/{year}")["groups"].astype(float)
            yield str(year), np.where(groups >= 0, groups, np.nan)
    else:
        raise ValueError(f"no pipeline output for layer {layer_id!r}")


def tiles(
    store: Store,
    out_dir: Path,
    layers: dict[str, LayerDefinition] | None = None,
    max_zoom: int = MAX_ZOOM,
) -> list[Path]:
    """One PMTiles file per layer map, at out_dir/<layer>/<name>.pmtiles."""
    grid = store.grid()
    written = []
    for layer in (layers or load_layers()).values():
        for name, values in _layer_maps(store, layer.id):
            path = out_dir / layer.id / f"{name}.pmtiles"
            write_pmtiles(path, values, grid, layer, max_zoom=max_zoom)
            written.append(path)
        logger.info("Wrote tiles for %s", layer.id)
    return written


def publish(out_dir: Path, tag: str) -> None:
    """Upload every PMTiles file to a GitHub Release, creating it if needed (ADR 0002).

    Release assets are flat, so each is named <layer>__<map>.pmtiles. A new release stays a
    draft until every file is uploaded, so a push to main never deploys half a release. Then
    Deploy is started on main: the github-pages environment only accepts deploys from main.
    """
    files = sorted(out_dir.rglob("*.pmtiles"))
    exists = subprocess.run(["gh", "release", "view", tag], capture_output=True).returncode == 0
    if not exists:
        subprocess.run(
            ["gh", "release", "create", tag, "--draft", "--title", tag, "--notes", ""], check=True
        )
    with tempfile.TemporaryDirectory() as staging:
        assets = []
        for path in files:
            asset = Path(staging) / f"{path.parent.name}__{path.name}"
            os.link(path, asset)
            assets.append(str(asset))
        for start in range(0, len(assets), 50):
            batch = assets[start : start + 50]
            subprocess.run(["gh", "release", "upload", tag, *batch, "--clobber"], check=True)
    if not exists:
        subprocess.run(["gh", "release", "edit", tag, "--draft=false"], check=True)
    subprocess.run(
        ["gh", "workflow", "run", "deploy.yml", "--ref", "main", "-f", f"tiles_release={tag}"],
        check=True,
    )


def run(
    source: Source,
    data_dir: Path,
    model_path: Path,
    tiles_dir: Path,
    years: list[int],
    block_km: float = 200,
    layers: dict[str, LayerDefinition] | None = None,
    max_zoom: int = MAX_ZOOM,
) -> list[Path]:
    """The whole pipeline, from extract to PMTiles; data_dir must already hold grid.json."""
    store = Store(data_dir)
    extract(source, store, years)
    report = train(store, model_path, block_km=block_km)
    logger.info("Model scores: %s", json.dumps(report, indent=2))
    predict(store, model_path)
    crop_effects(store)
    return tiles(store, tiles_dir, layers, max_zoom)
