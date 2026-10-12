"""Earth Engine Source chunking, with Earth Engine replaced by a fake that records requests."""

import io
from unittest.mock import MagicMock

import numpy as np
import pytest

from green.crops import CROP_GROUPS
from green.gee import CHUNK, FINE_CHUNK, EarthEngineSource
from green.grid import REGIONS
from green.sources import SOIL_LAYERS

FIELDS = ["natural", "cover", *CROP_GROUPS, *SOIL_LAYERS]


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


def test_ohio_valley_is_241_by_145_cells():
    grid = REGIONS["ohio_valley"]
    assert (grid.width, grid.height) == (241, 145)
    xmin, ymin, xmax, ymax = grid.bounds
    assert xmin <= -88 < xmin + 1 / 24 and xmax >= -78 > xmax - 1 / 24
    assert ymin <= 36 < ymin + 1 / 24 and ymax >= 42 > ymax - 1 / 24


@pytest.mark.parametrize("fetch", ["land_cover", "crop_shares"])
def test_30m_inputs_are_fetched_in_chunks_earth_engine_accepts(source, fetch):
    grid = REGIONS["ohio_valley"]
    result = source.land_cover(grid) if fetch == "land_cover" else source.crop_shares(grid, 2012)
    assert max(max(size) for size in source.sizes) == FINE_CHUNK
    assert sum(w * h for w, h in source.sizes) == grid.width * grid.height
    # Every chunk lands in the output: no cell is left masked.
    values = result[0] if fetch == "land_cover" else result
    assert not np.isnan(values).any()


def test_coarse_inputs_keep_larger_chunks(source):
    source.soil(REGIONS["ohio_valley"])
    assert max(max(size) for size in source.sizes) == CHUNK > FINE_CHUNK
