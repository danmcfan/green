"""Earth Engine Source, ported from planet-emu's extract script.

Each request asks computePixels for one chunk of the 4 km grid; a thread pool runs chunks in
parallel. Asset IDs, band names and NDVI scales were checked against Earth Engine in 2026-10.
"""

import calendar
import io
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from green.grid import Grid
from green.layers import LAYERS_FILE
from green.progress import Progress
from green.sources import CLIMATE_LAYERS, COVER_CLASSES, SOIL_LAYERS, Satellite

logger = logging.getLogger(__name__)

# Cells per side of one computePixels request, for soil and climate.
CHUNK = 128
# NDVI reduces a year of composites per cell. Over ohio_valley, VIIRS timed out once at 128
# cells and took 514 s on a retry, against 157 s at 64 cells (checked 2026-10-12, issue #20).
NDVI_CHUNK = 64
# NLCD is 30 m, so reduceResolution reads about 133 × 133 (17,750) fine pixels per
# 4 km cell.
#
# Larger 30 m chunks fail with "Reprojection output too large (7640x10274 pixels)": 65 cells
# failed and 49 worked (checked 2026-10-12, issue #20).
MAX_FINE_CHUNK = 49
FINE_CHUNK = 48
# The Earth Engine error for a chunk that covers too many fine pixels.
TOO_LARGE = "Reprojection output too large"
# Earth Engine's limit on fine pixels per coarse pixel in reduceResolution.
MAX_PIXELS = 65535
# A 4 km cell needs at least half of its fine pixels valid (docs/research §3).
MIN_VALID_SHARE = 0.5

SOIL_ASSETS = {
    "bulk_density": ("OpenLandMap/SOL/SOL_BULKDENS-FINEEARTH_USDA-4A1H_M/v02", 10),  # kg/m³
    "clay": ("OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02", 1),  # %
    "organic_carbon": ("OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02", 5),  # g/kg
    "ph": ("OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02", 0.1),
    "sand": ("OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02", 1),  # %
    "water": ("OpenLandMap/SOL/SOL_WATERCONTENT-33KPA_USDA-4B1C_M/v01", 1),  # %
}
DAYMET = "NASA/ORNL/DAYMET_V4"
DAYMET_BANDS = tuple(layer.removeprefix("climate_") for layer in CLIMATE_LAYERS)
NDVI_ASSETS = {
    # (asset, NDVI band, quality band, day-of-year band, NDVI scale)
    "modis": ("MODIS/061/MOD13A1", "NDVI", "SummaryQA", "DayOfYear", 0.0001),
    "viirs": (
        "NASA/VIIRS/002/VNP13A1",
        "NDVI",
        "pixel_reliability",
        "composite_day_of_the_year",
        # VIIRS v002 stores NDVI already scaled (checked on a live run, 2026-10).
        1,
    ),
}
NLCD_2001 = ("USGS/NLCD_RELEASES/2019_REL/NLCD", "2001")
NLCD_2021 = ("USGS/NLCD_RELEASES/2021_REL/NLCD", "2021")
NATURAL_NLCD = [41, 42, 43, 51, 52, 71, 72, 73, 74, 90, 95]
NLCD_COVER = {
    "forest": [41, 42, 43],
    "shrub": [51, 52],
    "grass": [71, 72, 73, 74],
    "wetland": [90, 95],
    "farm": [81, 82],
}


def initialize() -> None:
    import ee

    email = os.environ["GEE_EMAIL"]
    # .env paths are relative to the repo root, wherever the pipeline runs from.
    key_file = LAYERS_FILE.parent / os.environ.get("GEE_KEY_FILE", "keys/gee-service-account.json")
    ee.Initialize(ee.ServiceAccountCredentials(email, str(key_file)))


def _month_ranges(year: int) -> list[tuple[int, int]]:
    """First and last day of year of each month."""
    starts = [sum(calendar.monthrange(year, m)[1] for m in range(1, k)) + 1 for k in range(1, 13)]
    return [(s, s + calendar.monthrange(year, i + 1)[1] - 1) for i, s in enumerate(starts)]


class EarthEngineSource:
    name = "gee"

    def __init__(self, workers: int = 10):
        import ee

        self.ee = ee
        self.workers = workers

    def _fetch(
        self, label: str, image, grid: Grid, bands: list[str], chunk_size: int = CHUNK
    ) -> np.ndarray:
        """Pixels for every band, as (band, height, width) floats with NaN where masked."""
        out = np.full((len(bands), *grid.shape), np.nan, dtype=np.float32)

        def fill(row: int, col: int, sub: Grid) -> None:
            try:
                raw = self.ee.data.computePixels(
                    {"expression": image.select(bands), "fileFormat": "NPY", "grid": sub.ee_grid()}
                )
            except self.ee.EEException as e:
                # Near the edges of CONUS a chunk is turned in the 30 m Albers projection, so
                # it covers more fine pixels; split it in four and try again (issue #15).
                size = max(sub.width, sub.height)
                if TOO_LARGE not in str(e) or size == 1:
                    raise
                logger.warning("%s: chunk %d × %d too large, splitting", label, *sub.shape)
                for r, c, part in sub.chunks(math.ceil(size / 2)):
                    fill(row + r, col + c, part)
                return
            data = np.load(io.BytesIO(raw))
            for i, band in enumerate(bands):
                values = np.ma.filled(np.ma.asarray(data[band]).astype(np.float32), np.nan)
                out[i, row : row + sub.height, col : col + sub.width] = values

        def one(chunk: tuple[int, int, Grid]) -> None:
            fill(*chunk)
            progress.advance()

        chunks = grid.chunks(chunk_size)
        logger.info("Fetching %s: %d bands over %d chunks", label, len(bands), len(chunks))
        progress = Progress(label, len(chunks))
        with ThreadPoolExecutor(self.workers) as pool:
            list(pool.map(one, chunks))
        return out

    def _coarsen(self, image):
        return image.reduceResolution(self.ee.Reducer.mean(), maxPixels=MAX_PIXELS)

    def soil(self, grid: Grid) -> dict[str, np.ndarray]:
        ee = self.ee
        bands = []
        for name, (asset, scale) in SOIL_ASSETS.items():
            image = ee.Image(asset).select(["b0", "b30"]).multiply(scale)
            bands.append(image.rename([f"soil_{name}_0cm", f"soil_{name}_30cm"]))
        image = self._coarsen(ee.Image.cat(bands))
        values = self._fetch("soil", image, grid, list(SOIL_LAYERS))
        return dict(zip(SOIL_LAYERS, values, strict=True))

    def climate(self, grid: Grid, year: int) -> dict[str, np.ndarray]:
        ee = self.ee
        months = []
        for month in range(1, 13):
            start = ee.Date.fromYMD(year, month, 1)
            daily = ee.ImageCollection(DAYMET).filterDate(start, start.advance(1, "month"))
            # Monthly totals and means lose the native 1 km projection; restore it so
            # reduceResolution averages 1 km pixels into each 4 km cell.
            native = daily.first().projection()
            prcp = daily.select("prcp").sum()
            rest = daily.select([b for b in DAYMET_BANDS if b != "prcp"]).mean()
            names = [f"{layer}_{month}" for layer in CLIMATE_LAYERS]
            months.append(
                rest.addBands(prcp).select(list(DAYMET_BANDS), names).setDefaultProjection(native)
            )
        names = [f"{layer}_{m}" for m in range(1, 13) for layer in CLIMATE_LAYERS]
        values = self._fetch(f"climate {year}", self._coarsen(ee.Image.cat(months)), grid, names)
        values = values.reshape(12, len(CLIMATE_LAYERS), *grid.shape)
        return {layer: values[:, i] for i, layer in enumerate(CLIMATE_LAYERS)}

    def ndvi(self, grid: Grid, year: int, satellite: Satellite) -> tuple[np.ndarray, np.ndarray]:
        ee = self.ee
        asset, ndvi_band, qa_band, doy_band, scale = NDVI_ASSETS[satellite]
        # Composites starting in late December hold some early-January observations.
        collection = ee.ImageCollection(asset)
        composites = collection.filterDate(f"{year - 1}-12-01", f"{year + 1}-01-01")
        native = collection.first().projection()
        bands = []
        for month, (first, last) in enumerate(_month_ranges(year), start=1):

            def in_month(image, first=first, last=last):
                doy = image.select(doy_band)
                qa = image.select(qa_band)
                start = ee.Date(image.get("system:time_start"))
                # The day of year wraps to 1 in composites that cross New Year: a composite
                # from last year counts only wrapped days, one from this year only unwrapped.
                wrapped = doy.lt(start.getRelative("day", "year").add(1))
                from_last_year = ee.Image.constant(start.get("year").lt(year))
                this_year = wrapped.eq(from_last_year)
                # Keep good (0) and marginal (1) pixels observed this month (issue #7).
                keep = doy.gte(first).And(doy.lte(last)).And(qa.lte(1)).And(this_year)
                ndvi = image.select(ndvi_band).multiply(scale).rename("ndvi")
                good = qa.eq(0).toFloat().rename("good")
                return ndvi.addBands(good).updateMask(keep)

            in_range = composites.map(in_month)
            # Median NDVI, but the mean of the good flag: the share of good observations.
            fine = (
                in_range.select("ndvi")
                .median()
                .addBands(in_range.select("good").mean())
                .setDefaultProjection(native)
            )
            valid = fine.select("ndvi").mask().gt(0)
            coarse = self._coarsen(fine)
            share = self._coarsen(valid.unmask(0).toFloat())
            enough = share.gte(MIN_VALID_SHARE)
            bands.append(coarse.updateMask(enough).rename([f"ndvi_{month}", f"good_{month}"]))
        names = [f"{kind}_{m}" for m in range(1, 13) for kind in ("ndvi", "good")]
        values = self._fetch(
            f"{satellite} NDVI {year}", ee.Image.cat(bands), grid, names, NDVI_CHUNK
        )
        values = values.reshape(12, 2, *grid.shape)
        return values[:, 0], values[:, 1]

    def land_cover(self, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
        ee = self.ee

        def nlcd(spec):
            asset, year = spec
            return ee.ImageCollection(asset).filter(ee.Filter.eq("system:index", year)).first()

        first, latest = nlcd(NLCD_2001).select("landcover"), nlcd(NLCD_2021).select("landcover")
        ones = [1] * len(NATURAL_NLCD)
        natural = (
            first.remap(NATURAL_NLCD, ones, 0).And(latest.remap(NATURAL_NLCD, ones, 0))
        ).toFloat()
        codes = [c for cls in NLCD_COVER.values() for c in cls]
        classes = [COVER_CLASSES.index(k) for k, cls in NLCD_COVER.items() for _ in cls]
        other = COVER_CLASSES.index("other")
        cover = latest.remap(codes, classes, other).reduceResolution(
            ee.Reducer.mode(), maxPixels=MAX_PIXELS
        )
        image = self._coarsen(natural).rename("natural").addBands(cover.rename("cover"))
        share, cover_class = self._fetch(
            "land cover", image, grid, ["natural", "cover"], FINE_CHUNK
        )
        return share, np.nan_to_num(cover_class, nan=other).astype(np.int8)
