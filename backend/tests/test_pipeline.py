"""A tiny fixture run of the whole pipeline on synthetic data."""

import json
import subprocess

import joblib
import numpy as np
import pytest

from green import main
from green.layers import load_layers


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
    # CDL starts in 2008, so every year here has crop maps.
    assert sorted(p.stem for p in (tiles / "crop_type").glob("*.pmtiles")) == [
        "2010", "2011", "2012", "2013"
    ]  # fmt: skip


def test_saves_model_with_scaler_metadata_and_scores(run):
    saved = joblib.load(run / "models" / "small" / "model.joblib")
    assert "scale" in saved["pipeline"].named_steps
    assert saved["metadata"]["years"] == [2010, 2011, 2012, 2013]
    scores = saved["metrics"]
    for scheme in ("spatial", "temporal", "combined"):
        assert scores[scheme]["gbm"]["rmse"]["mean"] < scores[scheme]["mean"]["rmse"]["mean"]
    assert "climatology" in scores["temporal"]


def test_viirs_years_are_corrected_towards_modis(run):
    data = run / "data" / "small"
    with np.load(data / "ndvi_correction.npz") as f:
        slope, intercept = f["coeffs"][2, 6]  # grass, July
    # The synthetic VIIRS is 0.9·MODIS + 0.03, so the fit inverts it.
    assert slope == pytest.approx(1 / 0.9, rel=0.05)
    assert intercept == pytest.approx(-0.03 / 0.9, abs=0.02)


def test_crop_effect_only_on_single_crop_cells_with_regional_error(run):
    data = run / "data" / "small"
    with np.load(data / "crop_effect" / "2012.npz") as f:
        groups, effect = f["groups"], f["effect"]
    assert (groups >= 0).any() and (groups < 0).any()
    assert np.isnan(effect[:, groups < 0]).all()
    assert not np.isnan(effect[:, groups >= 0]).all()
    errors = json.loads((data / "crop_effect" / "regional_error.json").read_text())
    assert errors and all(e["rmse"] > 0 for e in errors.values())


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
