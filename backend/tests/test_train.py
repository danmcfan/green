import numpy as np

from green.train import (
    HOLDOUTS,
    Rows,
    _climatology,
    _training_departures,
    assign_folds,
    evaluate,
    held_out_years,
    metrics,
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
