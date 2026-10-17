"""Earth Engine Source chunking, with Earth Engine replaced by a fake that records requests."""

import io
import threading
import time
from unittest.mock import MagicMock

import numpy as np
import pytest

from green import gee
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


@pytest.mark.parametrize(
    "error", ["Reprojection output too large (7651x8815 pixels).", "User memory limit exceeded."]
)
def test_chunk_too_large_to_compute_is_split_and_retried(source, error):
    """Near the edges of CONUS a chunk covers more 30 m pixels, and Earth Engine refuses it."""
    accept = source.ee.data.computePixels

    def compute_pixels(request):
        dims = request["grid"]["dimensions"]
        if max(dims["width"], dims["height"]) > FINE_CHUNK // 2:
            raise source.ee.EEException(error)
        return accept(request)

    source.ee.EEException = Exception
    source.ee.data.computePixels = compute_pixels
    grid = REGIONS["ohio_valley"]
    share, _ = source.land_cover(grid)
    assert not np.isnan(share).any()
    assert max(max(size) for size in source.sizes) <= FINE_CHUNK // 2


def test_other_earth_engine_errors_are_not_retried(source):
    def compute_pixels(request):
        raise source.ee.EEException("Image.select: Band pattern 'b0' did not match any bands.")

    source.ee.EEException = Exception
    source.ee.data.computePixels = compute_pixels
    with pytest.raises(Exception, match="did not match"):
        source.land_cover(REGIONS["small"])


def _failing_first(source, failures):
    """Make computePixels raise each of `failures` in turn before it answers."""
    answer = source.ee.data.computePixels
    left = list(failures)
    calls = []

    def compute_pixels(request):
        calls.append(request)
        if left:
            raise left.pop(0)
        return answer(request)

    source.ee.data.computePixels = compute_pixels
    return calls


def test_a_request_that_times_out_is_retried(source, monkeypatch):
    """A hung request ends at the deadline (a TimeoutError) and is asked again."""
    monkeypatch.setattr("green.gee.RETRY_WAIT", 0)
    calls = _failing_first(source, [TimeoutError("read timed out")])
    share, _ = source.land_cover(REGIONS["small"])
    assert not np.isnan(share).any()
    assert len(calls) == len(source.sizes) + 1


def test_a_request_that_keeps_timing_out_fails_the_run(source, monkeypatch):
    monkeypatch.setattr("green.gee.RETRY_WAIT", 0)
    source.ee.EEException = Exception
    _failing_first(source, [TimeoutError("read timed out")] * 100)
    with pytest.raises(TimeoutError):
        source.land_cover(REGIONS["small"])


def test_initialize_sets_a_deadline_and_few_client_retries(monkeypatch):
    import ee

    from green import gee

    deadlines, retries = [], []
    monkeypatch.setenv("GEE_EMAIL", "someone@example.com")
    monkeypatch.setattr(ee, "ServiceAccountCredentials", MagicMock())
    monkeypatch.setattr(ee, "Initialize", MagicMock())
    monkeypatch.setattr(ee.data, "setDeadline", deadlines.append)
    monkeypatch.setattr(ee.data, "setMaxRetries", retries.append)
    gee.initialize()
    assert deadlines == [gee.DEADLINE_SECONDS * 1000]
    assert retries == [gee.CLIENT_RETRIES]
    # One stuck chunk must fail the run within about an hour and a half.
    attempts = (gee.RETRIES + 1) * (gee.CLIENT_RETRIES + 1)
    assert attempts * gee.DEADLINE_SECONDS + gee.RETRIES * gee.RETRY_WAIT <= 90 * 60


CONCURRENCY_ERROR = (
    "Too Many Requests: Exceeded Earth Engine concurrency limit. Your project is in Restricted"
    " Mode."
)


def _refuse_more_than_one_at_a_time(source):
    accept = source.ee.data.computePixels
    lock = threading.Lock()
    state = {"active": 0, "refused": 0}

    def compute_pixels(request):
        with lock:
            state["active"] += 1
            busy = state["active"] > 1
        try:
            if busy:
                state["refused"] += 1
                raise source.ee.EEException(CONCURRENCY_ERROR)
            time.sleep(0.01)
            return accept(request)
        finally:
            with lock:
                state["active"] -= 1

    source.ee.EEException = Exception
    source.ee.data.computePixels = compute_pixels
    return state


def test_concurrency_limit_slows_requests_down_instead_of_failing(source, monkeypatch):
    monkeypatch.setattr(gee, "THROTTLE_WAIT", 0)
    state = _refuse_more_than_one_at_a_time(source)
    values = source.soil(REGIONS["ohio_valley"])
    assert not np.isnan(values[SOIL_LAYERS[0]]).any()
    assert state["refused"] > 0
    assert source.throttle.limit == 1


def test_concurrency_limit_that_never_lifts_fails_with_when_the_quota_resets(source, monkeypatch):
    monkeypatch.setattr(gee, "THROTTLE_WAIT", 0)
    source.ee.EEException = Exception

    def compute_pixels(request):
        raise source.ee.EEException(CONCURRENCY_ERROR)

    source.ee.data.computePixels = compute_pixels
    with pytest.raises(gee.EarthEngineRestricted, match="first of the month"):
        source.soil(REGIONS["small"])
