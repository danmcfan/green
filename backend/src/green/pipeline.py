"""The pipeline steps: extract → train → predict → crop effect → tiles → publish."""

import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import joblib
import numpy as np

from green.crops import (
    crop_effect,
    near_farm,
    regional_map,
    regional_rmse,
    worst_error,
)
from green.layers import LayerDefinition, load_layers
from green.limits import check_tiles
from green.ndvi import FIRST_VIIRS_YEAR, apply_correction, fit_correction
from green.progress import Progress, step
from green.sources import CLIMATE_LAYERS, COVER_CLASSES, SOIL_LAYERS, Satellite, Source
from green.store import Store
from green.tiles import MAX_ZOOM, write_pmtiles
from green.train import HOLDOUTS, input_stack, natural_cells, train

logger = logging.getLogger(__name__)

# Terra stops collecting science data in about early 2027 (ADR 0005). Observed NDVI comes
# from MODIS up to this year and from corrected VIIRS after it (ADR 0007).
LAST_MODIS_YEAR = 2026
# Every year both satellites have data; the VIIRS correction is always fitted on all of them.
OVERLAP_YEARS = list(range(FIRST_VIIRS_YEAR, LAST_MODIS_YEAR + 1))
# Folder of the monthly NDVI each satellite gave per overlap year, kept for the VIIRS
# correction: <folder>/<satellite>/<year>.npz.
CORRECTION_YEARS = "ndvi_correction_years"


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

    def year_ndvi(year: int, satellite: Satellite) -> np.ndarray:
        # Each year is saved as soon as it is fetched, so a stopped run resumes where it was.
        def fetch():
            return {"ndvi": source.ndvi(grid, year, satellite)[0]}

        return _cached(store, f"{CORRECTION_YEARS}/{satellite}/{year}", source, fetch)["ndvi"]

    modis = np.stack([year_ndvi(y, "modis") for y in OVERLAP_YEARS])
    viirs = np.stack([year_ndvi(y, "viirs") for y in OVERLAP_YEARS])
    coeffs = fit_correction(modis, viirs, cover_class)
    store.save(
        "ndvi_correction",
        coeffs=coeffs,
        years=np.array(OVERLAP_YEARS),
        source=np.array(source.name),
    )
    return coeffs


def _cached(store: Store, name: str, source: Source, fetch: Callable[[], dict]) -> dict:
    """A saved extract file if it came from this source, else fetch and save it.

    A run that fails part way keeps every file it finished; `green clear` deletes them.
    """
    if store.path(name).exists():
        saved = store.load(name)
        if "source" in saved and str(saved.pop("source")) == source.name:
            logger.info("Using saved %s", name)
            return saved
    arrays = fetch()
    store.save(name, source=np.array(source.name), **arrays)
    return arrays


def extract(source: Source, store: Store, years: list[int]) -> None:
    """Fetch soil and land cover once, then climate and Observed NDVI per year."""
    grid = store.grid()
    logger.info("Extracting soil and land cover")
    _cached(store, "soil", source, lambda: source.soil(grid))

    def land_cover():
        natural_share, cover_class = source.land_cover(grid)
        return {"natural_share": natural_share, "cover_class": cover_class}

    cover_class = _cached(store, "land_cover", source, land_cover)["cover_class"]

    for i, year in enumerate(years, start=1):
        logger.info("Extracting %d (year %d of %d)", year, i, len(years))
        _cached(store, f"climate/{year}", source, lambda year=year: source.climate(grid, year))

        def ndvi(year=year):
            if year <= LAST_MODIS_YEAR:
                ndvi, good = source.ndvi(grid, year, "modis")
            else:
                coeffs = ndvi_correction(source, store, cover_class)
                ndvi, good = source.ndvi(grid, year, "viirs")
                ndvi = apply_correction(ndvi, cover_class, coeffs)
            return {"ndvi": ndvi, "good_share": good}

        _cached(store, f"ndvi/{year}", source, ndvi)


EXTRACTED = ["soil", "land_cover", "ndvi_correction", CORRECTION_YEARS, "climate", "ndvi"]


def clear(store: Store, only: list[str] | None = None) -> list[Path]:
    """Delete saved extract files, so the next run fetches them again.

    `only` names files or folders under the region, e.g. ["land_cover", "ndvi/2012", "climate"];
    without it every extract file goes. Training, prediction and tiles are made again on
    every run, so they are never cached and need no clearing.
    """
    removed = []
    for name in only or EXTRACTED:
        folder = store.root / name
        paths = sorted(folder.rglob("*.npz")) if folder.is_dir() else [store.path(name)]
        if only and not any(p.exists() for p in paths):
            raise FileNotFoundError(f"nothing saved for {name!r} in {store.root}")
        for path in paths:
            if path.exists():
                path.unlink()
                removed.append(path)
    return removed


def predict(store: Store, model_path: Path) -> None:
    """Predicted NDVI over every cell, and the residual on natural cells, per year."""
    model = joblib.load(model_path)
    soil = store.load("soil")
    natural = natural_cells(store)
    years = store.years("climate")
    progress = Progress("Predicting years", len(years), interval=0)
    for year in years:
        x = input_stack(soil, store.load(f"climate/{year}"))
        valid = ~np.isnan(x).any(axis=-1)
        predicted = np.full(valid.shape, np.nan)
        predicted[valid] = model["pipeline"].predict(x[valid])
        observed = store.load(f"ndvi/{year}")["ndvi"]
        residual = np.where(natural, observed - predicted, np.nan)
        store.save(f"predict/{year}", predicted=predicted, residual=residual)
        progress.advance()


def crop_effects(store: Store) -> dict:
    """Crop effect per year, and the model error next to farm land per region.

    Farm land is every cell whose main NLCD land cover class is farm (ADR 0006). The error is
    given for unseen places, unseen years and both (HOLDOUTS).
    """
    natural = natural_cells(store)
    farm = store.load("land_cover")["cover_class"] == COVER_CLASSES.index("farm")
    for year in store.years("predict"):
        observed = store.load(f"ndvi/{year}")["ndvi"]
        predicted = store.load(f"predict/{year}")["predicted"]
        store.save(f"crop_effect/{year}", effect=crop_effect(observed, predicted, farm))

    # Held-out predictions keep this honest: each cell was predicted by a model that never
    # saw its spatial block, its year, or both (ADR 0006).
    held_out = store.load("train/held_out")
    blocks = store.load("train/blocks")["blocks"]
    near = near_farm(farm, natural)
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
    else:
        raise ValueError(f"no pipeline output for layer {layer_id!r}")


def tiles(
    store: Store,
    out_dir: Path,
    layers: dict[str, LayerDefinition] | None = None,
    max_zoom: int = MAX_ZOOM,
) -> list[Path]:
    """One PMTiles file per layer map, at out_dir/<layer>/<name>.pmtiles.

    Fails if the files would not fit in a GitHub Release or on GitHub Pages, so a run that is
    too big is caught here rather than part way through publish.
    """
    grid = store.grid()
    written = []
    layers = list((layers or load_layers()).values())
    for i, layer in enumerate(layers, start=1):
        for name, values in _layer_maps(store, layer.id):
            path = out_dir / layer.id / f"{name}.pmtiles"
            write_pmtiles(path, values, grid, layer, max_zoom=max_zoom)
            written.append(path)
        logger.info("Wrote tiles for %s (layer %d of %d)", layer.id, i, len(layers))
    logger.info("Wrote %s", check_tiles(written))
    return written


def publish(out_dir: Path, tag: str) -> None:
    """Upload every PMTiles file to a GitHub Release, creating it if needed (ADR 0002).

    Release assets are flat, so each is named <layer>__<map>.pmtiles. A new release stays a
    draft until every file is uploaded, so a push to main never deploys half a release. Then
    Deploy is started on main: the github-pages environment only accepts deploys from main.
    Nothing is uploaded if the files would not fit in a Release or on Pages.
    """
    files = sorted(out_dir.rglob("*.pmtiles"))
    logger.info("Publishing %s", check_tiles(files))
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
    with step(f"Run {years[0]}–{years[-1]}"):
        with step("Extract"):
            extract(source, store, years)
        with step("Train"):
            report = train(store, model_path, block_km=block_km)
        logger.info("Model scores: %s", json.dumps(report, indent=2))
        with step("Predict"):
            predict(store, model_path)
        with step("Crop effect"):
            crop_effects(store)
        with step("Tiles"):
            return tiles(store, tiles_dir, layers, max_zoom)
