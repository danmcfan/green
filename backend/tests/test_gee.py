"""Earth Engine Source chunking, with Earth Engine replaced by a fake that records requests."""

import io
from unittest.mock import MagicMock

import numpy as np
import pytest

from green.gee import CHUNK, FINE_CHUNK, MAX_FINE_CHUNK, NDVI_CHUNK, EarthEngineSource
from green.grid import REGIONS
from green.sources import SOIL_LAYERS

NDVI_FIELDS = [f"{kind}_{m}" for m in range(1, 13) for kind in ("ndvi", "good")]
FIELDS = ["natural", "cover", *SOIL_LAYERS, *NDVI_FIELDS]


@pytest.fixture
def source():
    """A source whose computePixels returns ones and records each request's size."""
    sizes = []

    def compute_pixels(request):
        dims = request["grid"]["dimensions"]
        sizes.append((dims["width"], dims["height"]))
        data = np.ones((dims["height"], dims["width"]), dtype=[(f, "f4") for f in FIELDS])
        buffer = io.BytesIO()
        np.save(buffer, data)
        return buffer.getvalue()

    ee = MagicMock()
    ee.data.computePixels = compute_pixels
    src = EarthEngineSource(workers=2)
    src.ee = ee
    src.sizes = sizes
    return src


def test_30m_land_cover_is_fetched_in_chunks_earth_engine_accepts(source):
    grid = REGIONS["ohio_valley"]
    share, _ = source.land_cover(grid)
    largest = max(max(size) for size in source.sizes)
    assert largest <= MAX_FINE_CHUNK
    assert largest == FINE_CHUNK
    assert sum(w * h for w, h in source.sizes) == grid.width * grid.height
    # Every chunk lands in the output: no cell is left masked.
    assert not np.isnan(share).any()


def test_coarse_inputs_keep_larger_chunks(source):
    source.soil(REGIONS["ohio_valley"])
    assert max(max(size) for size in source.sizes) == CHUNK > FINE_CHUNK


@pytest.mark.parametrize("satellite", ["modis", "viirs"])
def test_ndvi_is_fetched_in_its_own_chunks(source, satellite):
    grid = REGIONS["ohio_valley"]
    ndvi, good = source.ndvi(grid, 2012, satellite)
    assert max(max(size) for size in source.sizes) == NDVI_CHUNK < CHUNK
    assert not np.isnan(ndvi).any() and not np.isnan(good).any()


def test_chunk_too_large_to_reproject_is_split_and_retried(source):
    """Near the edges of CONUS a chunk covers more 30 m pixels, and Earth Engine refuses it."""
    accept = source.ee.data.computePixels

    def compute_pixels(request):
        dims = request["grid"]["dimensions"]
        if max(dims["width"], dims["height"]) > FINE_CHUNK // 2:
            raise source.ee.EEException("Reprojection output too large (7651x8815 pixels).")
        return accept(request)

    source.ee.EEException = Exception
    source.ee.data.computePixels = compute_pixels
    grid = REGIONS["ohio_valley"]
    share, _ = source.land_cover(grid)
    assert not np.isnan(share).any()
    assert max(max(size) for size in source.sizes) <= FINE_CHUNK // 2


def test_other_earth_engine_errors_are_not_retried(source):
    def compute_pixels(request):
        raise source.ee.EEException("User memory limit exceeded.")

    source.ee.EEException = Exception
    source.ee.data.computePixels = compute_pixels
    with pytest.raises(Exception, match="memory"):
        source.land_cover(REGIONS["small"])
