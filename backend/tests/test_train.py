import numpy as np
import pytest

from green.sources import CLIMATE_LAYERS, SOIL_LAYERS
from green.train import (
    HOLDOUTS,
    INPUT_LAYERS,
    Rows,
    _climatology,
    _training_departures,
    assign_folds,
    departure_skill,
    evaluate,
    held_out_years,
    input_stack,
    leave_one_year_out,
    metrics,
    run_size,
    sample_cells,
)


def test_folds_keep_each_block_together():
    blocks = np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5])
    folds = assign_folds(blocks, n_folds=3, seed=1)
    for block in np.unique(blocks):
        assert len(set(folds[blocks == block])) == 1
    assert set(folds) == {0, 1, 2}


def test_fewer_blocks_than_folds_gives_one_fold_per_block():
    folds = assign_folds(np.array([7, 7, 9]), n_folds=5, seed=0)
    assert sorted(set(folds)) == [0, 1]


def test_last_three_years_held_out_when_there_are_enough():
    assert held_out_years(list(range(2001, 2025))) == [2022, 2023, 2024]


def test_short_records_hold_out_one_year():
    assert held_out_years([2011, 2012]) == [2012]


def test_metrics():
    m = metrics(np.array([0.0, 1.0]), np.array([0.0, 0.5]))
    assert m["rmse"] == np.sqrt(0.125)
    assert m["mae"] == 0.25
    assert m["r2"] == 0.5


def _rows(years: list[int], cells: int) -> Rows:
    rng = np.random.default_rng(0)
    year, month, cell = (a.ravel() for a in np.meshgrid(years, range(12), range(cells)))
    x = rng.normal(size=(len(year), 3))
    return Rows(x, x.sum(axis=1), np.ones(len(year)), year, month, cell // 4, cell % 4)


def test_held_out_predictions_cover_unseen_places_unseen_years_and_both():
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    folds = (rows.row >= 2).astype(int)
    _, held_out, predicted, holdout = evaluate(rows, folds, [2013], seed=0)

    assert set(holdout) == set(HOLDOUTS)
    assert not np.isnan(predicted).any()
    seen_year = held_out.year < 2013
    # Unseen places: every past-year row, predicted without its fold.
    assert (holdout == "spatial").sum() == (rows.year < 2013).sum()
    assert seen_year[holdout == "spatial"].all()
    # Unseen years and both: every held-out-year row, once each.
    for name in ("temporal", "combined"):
        assert (holdout == name).sum() == (rows.year == 2013).sum()
        assert not seen_year[holdout == name].any()


def test_one_spatial_block_still_gives_unseen_years():
    rows = _rows([2010, 2011, 2012, 2013], cells=4)
    _, _, _, holdout = evaluate(rows, np.zeros(len(rows.y), int), [2013], seed=0)
    assert set(holdout) == {"temporal"}


def test_unseen_years_score_climatology_plus_gbm_on_departures():
    # Each cell has its own level; Input layers only explain how a year departs from it.
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    level = np.random.default_rng(1).normal(size=16)[rows.row * 4 + rows.col] * 5
    rows.y = rows.y + level
    report, *_ = evaluate(rows, (rows.row >= 2).astype(int), [2013], seed=0)

    temporal = report["temporal"]
    assert temporal["climatology_gbm"]["rmse"]["mean"] < temporal["climatology"]["rmse"]["mean"]
    departure = report["temporal_departure_r2"]
    assert abs(departure["climatology"]) < 1e-9
    assert departure["climatology_gbm"] > 0.5
    assert "climatology_gbm" not in report["spatial"]


def test_departure_fit_skips_cells_with_only_one_training_year():
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    # Cell (0, 0) is only seen in 2010, so it has no Departure from the other training years.
    rows = rows.take((rows.row + rows.col > 0) | (rows.year == 2010))
    report, *_ = evaluate(rows, (rows.row >= 2).astype(int), [2013], seed=0)
    assert np.isfinite(report["temporal"]["climatology_gbm"]["rmse"]["mean"])


def _cell_rows(years: list[int], y: list[float], cols: list[int] | None = None) -> Rows:
    n = len(years)
    return Rows(
        x=np.zeros((n, 1)),
        y=np.array(y),
        weight=np.ones(n),
        year=np.array(years),
        month=np.zeros(n, dtype=int),
        row=np.zeros(n, dtype=int),
        col=np.array(cols if cols is not None else [0] * n),
    )


def test_training_departures_leave_out_the_rows_own_year():
    a, b = 0.7, 0.4
    departure = _training_departures(_cell_rows([2010, 2011], [a, b]))
    np.testing.assert_allclose(departure, [a - b, b - a])


def test_training_departure_is_missing_without_another_year():
    departure = _training_departures(_cell_rows([2010, 2010, 2011], [0.5, 0.6, 0.3], [1, 0, 0]))
    assert np.isnan(departure[0])
    np.testing.assert_allclose(departure[1:], [0.3, -0.3])


def test_test_time_climatology_uses_every_training_year():
    train = _cell_rows([2010, 2011], [0.7, 0.4])
    test = _cell_rows([2012], [0.0])
    np.testing.assert_allclose(_climatology(train, test, fallback=0.0), [0.55])


def _climate(prcp: list[float], **others: list[float]) -> dict[str, np.ndarray]:
    """One cell's climate for a year, with every layer not given at zero."""
    climate = {name: np.zeros((12, 1, 1)) for name in CLIMATE_LAYERS}
    for name, values in {"prcp": prcp, **others}.items():
        climate[f"climate_{name}"] = np.array(values, dtype=float).reshape(12, 1, 1)
    return climate


SOIL = {name: np.zeros((1, 1)) for name in SOIL_LAYERS}
RECENT = INPUT_LAYERS.index("recent_prcp")


def test_recent_rainfall_is_the_mean_over_the_previous_three_months():
    x = input_stack(SOIL, _climate(list(range(101, 113))), _climate(list(range(1, 13))))

    # January looks back to October-December of last year; April to January-March.
    expected = [(10 + 11 + 12) / 3, (11 + 12 + 101) / 3, (12 + 101 + 102) / 3]
    expected += list(range(102, 111))
    np.testing.assert_allclose(x[:, 0, 0, RECENT], expected)


def test_recent_rainfall_is_missing_early_in_the_year_without_last_years_climate():
    x = input_stack(SOIL, _climate(list(range(101, 113))), None)

    assert np.isnan(x[:3, 0, 0, RECENT]).all()
    assert x[3, 0, 0, RECENT] == 102


def test_last_months_rainfall_tmax_and_vp_look_back_too():
    this = _climate(list(range(101, 113)), tmax=list(range(201, 213)), vp=list(range(301, 313)))
    last = _climate(list(range(1, 13)), tmax=list(range(21, 33)), vp=list(range(31, 43)))
    x = input_stack(SOIL, this, last)[:, 0, 0]

    np.testing.assert_allclose(x[:2, INPUT_LAYERS.index("recent_prcp_1m")], [12, 101])
    np.testing.assert_allclose(x[0, INPUT_LAYERS.index("recent_tmax")], (30 + 31 + 32) / 3)
    np.testing.assert_allclose(x[4, INPUT_LAYERS.index("recent_vp")], (302 + 303 + 304) / 3)


def test_leave_one_year_out_scores_the_departure_for_every_year():
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    rows.y = rows.y + np.random.default_rng(1).normal(size=16)[rows.row * 4 + rows.col] * 5
    report = leave_one_year_out(rows, seed=0)

    assert sorted(report["years"]) == [2010, 2011, 2012, 2013]
    scores = list(report["years"].values())
    assert all(s > 0.5 for s in scores)
    assert report["mean"] == pytest.approx(np.mean(scores))
    assert report["above_zero"] == 4
    assert report["passes"]


def test_leave_one_year_out_fails_when_input_layers_say_nothing_about_the_departure():
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    rows.y = np.random.default_rng(2).normal(size=len(rows.y))
    assert not leave_one_year_out(rows, seed=0)["passes"]


def test_departure_skill_scores_unseen_years_places_and_both():
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    rows.y = rows.y + np.random.default_rng(1).normal(size=16)[rows.row * 4 + rows.col] * 5
    folds = (rows.row >= 2).astype(int)
    skill = departure_skill(rows, folds, seed=0)

    expected_tests = {"unseen_years": 4, "unseen_places": 2, "unseen_years_and_places": 8}
    for holdout, tests in expected_tests.items():
        assert skill[holdout]["tests"] == tests
        assert skill[holdout]["above_zero"] == tests
        assert skill[holdout]["r2"] > 0.5
        assert skill[holdout]["rmse"] < skill[holdout]["rmse_zero"]


def test_departure_skill_fits_on_a_sample_of_rows():
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    folds = (rows.row >= 2).astype(int)
    assert departure_skill(rows, folds, seed=0, sample=300)["sample_rows"] == 300
    assert departure_skill(rows, folds, seed=0)["sample_rows"] == len(rows.y)


def test_departure_skill_is_near_zero_when_input_layers_say_nothing():
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    rows.y = np.random.default_rng(2).normal(size=len(rows.y))
    skill = departure_skill(rows, (rows.row >= 2).astype(int), seed=0)
    assert skill["unseen_years"]["r2"] < 0.1


def test_departure_skill_skips_unseen_places_with_one_spatial_block():
    rows = _rows([2010, 2011, 2012, 2013], cells=16)
    skill = departure_skill(rows, np.zeros(len(rows.y), int), seed=0)
    assert set(skill) == {"sample_rows", "unseen_years"}


def test_run_size_counts_natural_cells_and_spatial_blocks_big_enough_to_score():
    # Two spatial blocks of 10 by 10 cells.
    blocks = np.zeros((10, 20), dtype=int)
    blocks[:, 10:] = 1
    natural_share = np.zeros((10, 20))
    farm = np.zeros((10, 20), dtype=bool)
    # Left block: 90 natural cells, only the 10 in column 8 next to the farm column 9.
    natural_share[:, :9] = 0.75
    farm[:, 9] = True
    # Right block: 30 natural cells, all next to farm land, and some cells not natural enough.
    farm[:, [13, 17]] = True
    natural_share[:, [12, 14, 18]] = 0.9
    natural_share[:, 19] = 0.7
    assert run_size(natural_share, farm, blocks, [2011, 2012]) == {
        "natural_cells": 120,
        "blocks_with_50_natural_cells": 1,
        "blocks_with_25_natural_cells_next_to_farm": 1,
        "years": [2011, 2012],
    }


def test_cell_sample_keeps_a_fixed_seed_fraction_of_the_cells():
    cells = np.ones((200, 200), bool)
    cells[:, :50] = False
    picked = sample_cells(cells, 0.25, seed=0)
    assert not picked[:, :50].any()
    assert picked.sum() == pytest.approx(0.25 * cells.sum(), rel=0.05)
    assert (sample_cells(cells, 0.25, seed=0) == picked).all()
    assert (sample_cells(cells, 1, seed=0) == cells).all()


def test_cell_fraction_must_be_a_share_of_the_cells():
    with pytest.raises(ValueError):
        sample_cells(np.ones((2, 2), bool), 0, seed=0)
