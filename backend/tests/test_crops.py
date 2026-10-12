import numpy as np
import pytest

from green.crops import (
    CDL_GROUPS,
    CROP_GROUPS,
    CROP_TYPES,
    ROTATION,
    crop_effect,
    dominant_group,
    near_farm,
    regional_map,
    regional_rmse,
    worst_error,
)
from green.layers import load_layers


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
    fractions[2, 0, 2], fractions[0, 0, 2] = 0.5, 0.5  # mixed
    assert dominant_group(fractions).tolist() == [[0, -1, -1]]


def _shares(**groups: float) -> np.ndarray:
    fractions = np.zeros((9, 1, 1))
    for name, share in groups.items():
        fractions[CROP_GROUPS.index(name), 0, 0] = share
    return fractions


@pytest.mark.parametrize(
    ("shares", "expected"),
    [
        ({"corn": 0.8, "soybeans": 0.15}, 0),  # one group first, even when corn + soybeans pass
        ({"soybeans": 0.76, "corn": 0.2}, 1),
        ({"corn": 0.45, "soybeans": 0.35}, ROTATION),
        ({"corn": 0.375, "soybeans": 0.375}, ROTATION),
        ({"corn": 0.4, "soybeans": 0.3}, -1),
        ({"winter_wheat": 0.5, "corn": 0.3}, -1),
    ],
)
def test_dominant_group_gives_corn_soybean_cells_the_rotation(shares, expected):
    assert dominant_group(_shares(**shares)).tolist() == [[expected]]


def test_rotation_is_the_last_crop_type_after_the_nine_crop_groups():
    assert CROP_TYPES[: len(CROP_GROUPS)] == CROP_GROUPS
    assert CROP_TYPES[ROTATION] == "corn_soybean"
    assert len(CROP_TYPES) == 10


def test_rotation_cells_get_a_crop_effect():
    groups = dominant_group(_shares(corn=0.45, soybeans=0.35))
    effect = crop_effect(np.full((12, 1, 1), 0.7), np.full((12, 1, 1), 0.5), groups)
    assert effect[:, 0, 0] == pytest.approx(np.full(12, 0.2))
    none = dominant_group(_shares(corn=0.4, soybeans=0.3))
    assert np.isnan(crop_effect(np.full((12, 1, 1), 0.7), np.full((12, 1, 1), 0.5), none)).all()


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


def test_regional_map_gives_each_cell_its_block_rmse():
    blocks = np.array([[0, 0, 1], [2, 2, 1]])
    errors = {0: {"rmse": 0.1, "cells": 2}, 1: {"rmse": 0.3, "cells": 1}}
    expected = np.array([[0.1, 0.1, 0.3], [np.nan, np.nan, 0.3]])
    np.testing.assert_array_equal(regional_map(errors, blocks), expected)


def test_crop_type_layer_names_one_color_per_crop_type():
    crop_type = load_layers()["crop_type"]
    names = [name.lower().replace(" ", "_").replace("/", "_") for name in crop_type.categories]
    assert names == list(CROP_TYPES)
    assert len(crop_type.colors) == len(CROP_TYPES)
    assert len(set(crop_type.colors)) == len(CROP_TYPES)
    assert crop_type.range == (0, len(CROP_TYPES) - 1)


def test_worst_error_takes_the_largest_rmse_over_holdouts_for_each_block():
    errors = {
        "spatial": {0: {"rmse": 0.1, "cells": 4}, 1: {"rmse": 0.3, "cells": 2}},
        "temporal": {0: {"rmse": 0.2, "cells": 3}},
        "combined": {2: {"rmse": 0.05, "cells": 1}},
    }
    assert worst_error(errors) == {
        0: {"rmse": 0.2, "cells": 3},
        1: {"rmse": 0.3, "cells": 2},
        2: {"rmse": 0.05, "cells": 1},
    }
