"""A tiny fixture run of the whole pipeline on synthetic data."""

import json
import subprocess

import joblib
import numpy as np
import pytest

from green import main, pipeline
from green.grid import REGIONS
from green.layers import load_layers
from green.ndvi import FIRST_VIIRS_YEAR
from green.pipeline import LAST_MODIS_YEAR
from green.sources import COVER_CLASSES, SyntheticSource
from green.store import Store

# The first year after Terra stops, so the first that needs the VIIRS correction.
VIIRS_YEAR = LAST_MODIS_YEAR + 1


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("run")
    main(
        [
            "run",
            "--region", "small",
            "--source", "synthetic",
            "--start", "2010",
            "--end", "2013",
            "--block-km", "25",
            "--max-zoom", "3",
            "--data-dir", str(root / "data"),
            "--models-dir", str(root / "models"),
            "--tiles-dir", str(root / "tiles"),
        ]
    )  # fmt: skip
    return root


def test_writes_pmtiles_for_every_layer(run):
    tiles = run / "tiles" / "small"
    for layer_id in load_layers():
        assert any((tiles / layer_id).glob("*.pmtiles")), layer_id
    assert (tiles / "soil_clay_0cm" / "soil_clay_0cm.pmtiles").exists()
    assert len(list((tiles / "observed_ndvi").glob("*.pmtiles"))) == 4 * 12
    assert len(list((tiles / "crop_effect").glob("*.pmtiles"))) == 4 * 12


def test_saves_model_with_scaler_metadata_and_scores(run):
    saved = joblib.load(run / "models" / "small" / "model.joblib")
    assert "scale" in saved["pipeline"].named_steps
    assert saved["metadata"]["years"] == [2010, 2011, 2012, 2013]
    scores = saved["metrics"]
    for scheme in ("spatial", "temporal", "combined"):
        assert scores[scheme]["gbm"]["rmse"]["mean"] < scores[scheme]["mean"]["rmse"]["mean"]
    assert "climatology" in scores["temporal"]


def test_viirs_years_are_corrected_towards_modis(tmp_path):
    coeffs, _ = _extract(tmp_path, [VIIRS_YEAR])
    slope, intercept = coeffs[2, 6]  # grass, July
    # The synthetic VIIRS is 0.9·MODIS + 0.03, so the fit inverts it.
    assert slope == pytest.approx(1 / 0.9, rel=0.05)
    assert intercept == pytest.approx(-0.03 / 0.9, abs=0.02)


def test_crop_effect_only_on_farm_land_with_regional_error(run):
    data = run / "data" / "small"
    with np.load(data / "land_cover.npz") as f:
        farm = f["cover_class"] == COVER_CLASSES.index("farm")
    with np.load(data / "crop_effect" / "2012.npz") as f:
        effect = f["effect"]
    assert farm.any() and (~farm).any()
    assert np.isnan(effect[:, ~farm]).all()
    assert not np.isnan(effect[:, farm]).all()
    errors = json.loads((data / "crop_effect" / "regional_error.json").read_text())
    # The error next to farm land on unseen places, unseen years and both (ADR 0006).
    assert set(errors) == {"spatial", "temporal", "combined"}
    for by_block in errors.values():
        assert by_block and all(e["rmse"] > 0 for e in by_block.values())


def test_publish_keeps_a_new_release_draft_until_every_file_is_uploaded(tmp_path, monkeypatch):
    from green import pipeline

    for layer in ["observed_ndvi", "crop_effect"]:
        (tmp_path / layer).mkdir()
        (tmp_path / layer / "2012-07.pmtiles").write_bytes(b"")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1 if args[2] == "view" else 0)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    pipeline.publish(tmp_path, "tiles-test")

    assert [args[1:3] for args in calls] == [
        ["release", "view"],
        ["release", "create"],
        ["release", "upload"],
        ["release", "edit"],
        ["workflow", "run"],
    ]
    assert "--draft" in calls[1]
    assert calls[3][-1] == "--draft=false"


def test_publish_deploys_the_release_from_main(tmp_path, monkeypatch):
    # The github-pages environment only accepts deploys from main, so a Release event
    # (which runs on the tag) cannot deploy; publish starts Deploy on main instead.
    from green import pipeline

    (tmp_path / "observed_ndvi").mkdir()
    (tmp_path / "observed_ndvi" / "2012-07.pmtiles").write_bytes(b"")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    pipeline.publish(tmp_path, "tiles-test")

    assert calls[-1] == [
        "gh",
        "workflow",
        "run",
        "deploy.yml",
        "--ref",
        "main",
        "-f",
        "tiles_release=tiles-test",
    ]


def test_tiles_fails_when_the_files_would_not_fit_in_a_release(run, tmp_path, monkeypatch):
    from green import limits, pipeline
    from green.store import Store

    monkeypatch.setattr(limits, "RELEASE_MAX_ASSETS", 12)
    layers = {"observed_ndvi": load_layers()["observed_ndvi"]}
    store = Store(run / "data" / "small")
    with pytest.raises(limits.TilesOverLimitError, match="48 PMTiles files"):
        pipeline.tiles(store, tmp_path, layers, max_zoom=2)


def test_publish_uploads_nothing_when_the_files_would_not_fit_on_pages(tmp_path, monkeypatch):
    from green import limits, pipeline

    (tmp_path / "observed_ndvi").mkdir()
    (tmp_path / "observed_ndvi" / "2012-07.pmtiles").write_bytes(b"x" * 100)
    monkeypatch.setattr(limits, "PAGES_MAX_SITE_BYTES", 50)
    calls = []
    monkeypatch.setattr(pipeline.subprocess, "run", lambda args, **kwargs: calls.append(args))

    with pytest.raises(limits.TilesOverLimitError, match="Pages"):
        pipeline.publish(tmp_path, "tiles-test")
    assert calls == []


class CountingSource(SyntheticSource):
    """Synthetic data that records which years of NDVI it was asked for, per satellite."""

    def __init__(self, seed=0):
        super().__init__(seed)
        self.fetched = []

    def ndvi(self, grid, year, satellite):
        self.fetched.append((year, satellite))
        return super().ndvi(grid, year, satellite)


def _extract(root, years, source=None):
    store = Store(root)
    store.save_grid(REGIONS["small"])
    pipeline.extract(source or SyntheticSource(), store, years)
    with np.load(store.path("ndvi_correction")) as f:
        return f["coeffs"], f["years"]


def test_viirs_correction_is_fitted_on_every_overlap_year_whatever_years_a_run_covers(tmp_path):
    # ADR 0005: two runs with different years must give the same Observed NDVI.
    one_year, fitted_on = _extract(tmp_path / "a", [VIIRS_YEAR])
    other_years, _ = _extract(tmp_path / "b", [2011, VIIRS_YEAR, VIIRS_YEAR + 1])
    np.testing.assert_array_equal(one_year, other_years)
    assert list(fitted_on) == list(range(FIRST_VIIRS_YEAR, LAST_MODIS_YEAR + 1))


def test_viirs_correction_is_fitted_once_per_region_and_reused(tmp_path):
    first, _ = _extract(tmp_path, [VIIRS_YEAR])
    source = CountingSource()
    again, _ = _extract(tmp_path, [VIIRS_YEAR + 1, VIIRS_YEAR + 2], source)
    np.testing.assert_array_equal(first, again)
    assert sorted(source.fetched) == [(VIIRS_YEAR + 1, "viirs"), (VIIRS_YEAR + 2, "viirs")]


def test_viirs_correction_from_another_source_is_not_reused(tmp_path):
    # A synthetic run must not leave coefficients that a later run on other data applies.
    first, _ = _extract(tmp_path, [VIIRS_YEAR])
    source = CountingSource(seed=1)
    again, _ = _extract(tmp_path, [VIIRS_YEAR + 1], source)
    assert not np.array_equal(first, again)
    assert (2012, "viirs") in source.fetched and (2026, "modis") in source.fetched
    with np.load(Store(tmp_path).path("ndvi_correction")) as f:
        assert str(f["source"]) == "synthetic-1"


def test_every_year_terra_covers_uses_modis_and_fits_no_correction(tmp_path):
    # ADR 0007: VIIRS is only needed once Terra stops.
    source = CountingSource()
    store = Store(tmp_path)
    store.save_grid(REGIONS["small"])
    pipeline.extract(source, store, [2011, 2012, LAST_MODIS_YEAR])
    assert sorted(source.fetched) == [(2011, "modis"), (2012, "modis"), (LAST_MODIS_YEAR, "modis")]
    assert not store.path("ndvi_correction").exists()


def _store(root):
    store = Store(root)
    store.save_grid(REGIONS["small"])
    return store


def test_extract_reuses_every_file_a_failed_or_earlier_run_saved(tmp_path):
    store = _store(tmp_path)
    pipeline.extract(SyntheticSource(), store, [2010, 2011])
    source = CountingSource()
    source.soil = source.land_cover = source.climate = None  # never called
    pipeline.extract(source, store, [2010, 2011])
    assert source.fetched == []


def test_extract_fetches_again_what_another_source_saved(tmp_path):
    store = _store(tmp_path)
    pipeline.extract(SyntheticSource(), store, [2010])
    source = CountingSource(seed=1)
    pipeline.extract(source, store, [2010])
    assert source.fetched == [(2010, "modis")]


def test_clear_only_deletes_the_named_files_and_folders(tmp_path):
    store = _store(tmp_path)
    pipeline.extract(SyntheticSource(), store, [2010, 2011])
    removed = pipeline.clear(store, ["ndvi/2011", "climate"])
    assert sorted(p.relative_to(tmp_path).as_posix() for p in removed) == [
        "climate/2010.npz",
        "climate/2011.npz",
        "ndvi/2011.npz",
    ]
    source = CountingSource()
    pipeline.extract(source, store, [2010, 2011])
    assert source.fetched == [(2011, "modis")]


def test_clear_deletes_every_extract_file_but_keeps_the_grid(tmp_path):
    store = _store(tmp_path)
    pipeline.extract(SyntheticSource(), store, [2012])
    pipeline.clear(store)
    assert not list(tmp_path.rglob("*.npz"))
    assert (tmp_path / "grid.json").exists()


def test_clear_fails_on_a_name_with_nothing_saved(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(FileNotFoundError, match="land_cvoer"):
        pipeline.clear(store, ["land_cvoer"])


class StoppingSource(CountingSource):
    """Synthetic data that stops the run, as Ctrl-C or a failed request would, after `limit`."""

    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def ndvi(self, grid, year, satellite):
        if len(self.fetched) == self.limit:
            raise KeyboardInterrupt
        return super().ndvi(grid, year, satellite)


def test_a_stopped_viirs_correction_resumes_from_the_years_it_fetched(tmp_path):
    whole, _ = _extract(tmp_path / "whole", [VIIRS_YEAR])
    store = _store(tmp_path / "resumed")
    stopping = StoppingSource(limit=20)
    with pytest.raises(KeyboardInterrupt):
        pipeline.extract(stopping, store, [VIIRS_YEAR])
    source = CountingSource()
    resumed, _ = _extract(tmp_path / "resumed", [VIIRS_YEAR], source)
    years = range(FIRST_VIIRS_YEAR, LAST_MODIS_YEAR + 1)
    overlap = {(y, s) for s in ("modis", "viirs") for y in years}
    # Plus the run's own year, which only VIIRS covers.
    expected = [*(overlap - set(stopping.fetched)), (VIIRS_YEAR, "viirs")]
    assert sorted(source.fetched) == sorted(expected)
    np.testing.assert_array_equal(whole, resumed)


def test_saved_correction_years_from_another_source_are_fetched_again(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        pipeline.extract(StoppingSource(limit=4), store, [VIIRS_YEAR])
    source = CountingSource(seed=1)
    pipeline.extract(source, store, [VIIRS_YEAR])
    assert len(source.fetched) == 2 * len(range(FIRST_VIIRS_YEAR, LAST_MODIS_YEAR + 1)) + 1


def test_clear_deletes_the_saved_correction_years(tmp_path):
    store = _store(tmp_path)
    pipeline.extract(SyntheticSource(), store, [VIIRS_YEAR])
    removed = pipeline.clear(store, ["ndvi_correction_years/viirs"])
    assert {p.parent.name for p in removed} == {"viirs"}
    pipeline.clear(store)
    assert not list(tmp_path.rglob("*.npz"))
