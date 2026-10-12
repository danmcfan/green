"""Crop groups from the Cropland Data Layer and the Crop effect (ADR 0006)."""

import numpy as np

CROP_GROUPS = (
    "corn",
    "soybeans",
    "winter_wheat",
    "spring_wheat",
    "cotton",
    "alfalfa",
    "other_hay_pasture",
    "rice",
    "other_crops",
)

_NAMED = {
    "corn": (1, 12, 13),
    "soybeans": (5,),
    "winter_wheat": (24,),
    "spring_wheat": (23,),
    "cotton": (2,),
    "alfalfa": (36,),
    # CDL takes grass/pasture (176) from NLCD 81.
    "other_hay_pasture": (37, 176),
    "rice": (3,),
}
# Every other cultivated CDL class (1–61, 66–77, 204–254), double crops included.
_CULTIVATED = (*range(1, 62), *range(66, 78), *range(204, 255))
_TAKEN = {code for codes in _NAMED.values() for code in codes}

CDL_GROUPS: dict[str, tuple[int, ...]] = {
    **_NAMED,
    "other_crops": tuple(c for c in _CULTIVATED if c not in _TAKEN),
}

# Crop type categories: the 9 crop groups, then corn/soybean rotation. The rotation is a
# Crop type only, not a crop group to fetch: it is read from the corn and soybean shares.
CROP_TYPES = (*CROP_GROUPS, "corn_soybean")
ROTATION = CROP_TYPES.index("corn_soybean")
_CORN, _SOYBEANS = CROP_GROUPS.index("corn"), CROP_GROUPS.index("soybeans")

FIRST_CDL_YEAR = 2008
DOMINANT_SHARE = 0.75


def dominant_group(fractions: np.ndarray, share: float = DOMINANT_SHARE) -> np.ndarray:
    """Crop type index of each cell (CROP_TYPES order), or -1 for none (ADR 0006).

    A cell takes the crop group covering at least `share` of it. Failing that, it takes
    ROTATION when corn and soybeans together cover at least `share`.
    `fractions` has one (height, width) band per crop group, in CROP_GROUPS order.
    """
    fractions = np.nan_to_num(fractions)
    best = fractions.argmax(axis=0)
    rotation = fractions[_CORN] + fractions[_SOYBEANS] >= share
    single = fractions.max(axis=0) >= share
    return np.where(single, best, np.where(rotation, ROTATION, -1)).astype(np.int8)


def crop_effect(observed: np.ndarray, predicted: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Observed minus Predicted NDVI on cells with a Crop type; empty elsewhere."""
    return np.where(groups >= 0, observed - predicted, np.nan)


def near_farm(farm: np.ndarray, natural: np.ndarray) -> np.ndarray:
    """Natural cells with farm land in one of their eight neighbours."""
    padded = np.pad(farm, 1)
    height, width = farm.shape
    touching = np.zeros_like(farm)
    for dy in range(3):
        for dx in range(3):
            touching |= padded[dy : dy + height, dx : dx + width]
    return touching & natural & ~farm


def regional_rmse(
    observed: np.ndarray, predicted: np.ndarray, mask: np.ndarray, blocks: np.ndarray
) -> dict[int, dict]:
    """RMSE of Predicted NDVI within each block, over masked cells with values.

    Arrays may carry leading (year, month) axes; mask and blocks broadcast over them.
    """
    error = (observed - predicted) ** 2
    blocks = np.broadcast_to(blocks, error.shape)
    keep = np.broadcast_to(mask, error.shape) & ~np.isnan(error)
    result = {}
    for block in np.unique(blocks[keep]):
        sel = keep & (blocks == block)
        result[int(block)] = {
            "rmse": float(np.sqrt(error[sel].mean())),
            "cells": int(sel.sum()),
        }
    return result


def worst_error(errors: dict[str, dict[int, dict]]) -> dict[int, dict]:
    """For each block, the regional_rmse entry with the largest RMSE over every holdout."""
    worst: dict[int, dict] = {}
    for by_block in errors.values():
        for block, error in by_block.items():
            if block not in worst or error["rmse"] > worst[block]["rmse"]:
                worst[block] = error
    return worst


def regional_map(errors: dict[int, dict], blocks: np.ndarray) -> np.ndarray:
    """Each cell's block RMSE from regional_rmse; empty where its block has none."""
    result = np.full(blocks.shape, np.nan)
    for block, error in errors.items():
        result[blocks == block] = error["rmse"]
    return result
