import numpy as np
import pytest

from green.crops import (
    CDL_GROUPS,
    CROP_GROUPS,
    crop_effect,
    dominant_group,
    near_farm,
    regional_rmse,
)


def test_nine_crop_groups_with_disjoint_cdl_codes():
    assert len(CROP_GROUPS) == 9
    assert set(CDL_GROUPS) == set(CROP_GROUPS)
    seen = [code for codes in CDL_GROUPS.values() for code in codes]
    assert len(seen) == len(set(seen))
    assert 1 in CDL_GROUPS["corn"] and 5 in CDL_GROUPS["soybeans"]


def test_dominant_group_keeps_cells_with_75_percent_of_one_group():
    fractions = np.zeros((9, 1, 3))
    fractions[0, 0, 0] = 0.8  # mostly corn
    fractions[1, 0, 1] = 0.74  # just short
    fractions[0, 0, 2], fractions[1, 0, 2] = 0.5, 0.5  # mixed
    assert dominant_group(fractions).tolist() == [[0, -1, -1]]


def test_crop_effect_is_observed_minus_predicted_on_crop_cells_only():
    observed = np.full((12, 1, 2), 0.7)
    predicted = np.full((12, 1, 2), 0.5)
    groups = np.array([[2, -1]])
    effect = crop_effect(observed, predicted, groups)
    assert effect[:, 0, 0] == pytest.approx(np.full(12, 0.2))
    assert np.isnan(effect[:, 0, 1]).all()


def test_near_farm_marks_natural_cells_touching_farm_land():
    farm = np.zeros((3, 4), bool)
    farm[1, 1] = True
    natural = ~farm
    natural[0, 0] = False
    near = near_farm(farm, natural)
    assert near.tolist() == [
        [False, True, True, False],
        [True, False, True, False],
        [True, True, True, False],
    ]


def test_regional_rmse_per_block():
    observed = np.array([[0.5, 0.5, 0.5, 0.5]])
    predicted = np.array([[0.4, 0.6, 0.5, 0.2]])
    mask = np.array([[True, True, False, True]])
    blocks = np.array([[0, 0, 1, 1]])
    errors = regional_rmse(observed, predicted, mask, blocks)
    assert errors[0] == {"rmse": pytest.approx(0.1), "cells": 2}
    assert errors[1] == {"rmse": pytest.approx(0.3), "cells": 1}
