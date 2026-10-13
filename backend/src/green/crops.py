"""The Crop effect on farm land, and the model error next to it (ADR 0006)."""

import numpy as np


def crop_effect(observed: np.ndarray, predicted: np.ndarray, farm: np.ndarray) -> np.ndarray:
    """Observed minus Predicted NDVI on farm cells; empty elsewhere."""
    return np.where(farm, observed - predicted, np.nan)


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
