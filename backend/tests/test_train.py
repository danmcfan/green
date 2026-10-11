import numpy as np

from green.train import assign_folds, held_out_years, metrics


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
