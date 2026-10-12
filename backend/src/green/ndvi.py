"""Observed NDVI: VIIRS-to-MODIS correction and quality weights (ADR 0005)."""

import numpy as np

FIRST_VIIRS_YEAR = 2012


def fit_correction(modis: np.ndarray, viirs: np.ndarray, classes: np.ndarray) -> np.ndarray:
    """Least-squares fit modis ≈ slope · viirs + intercept, per land cover class and month.

    `modis` and `viirs` are (year, month, height, width) over years both satellites cover.
    Returns (class, month, 2) of (slope, intercept); classes without data get (1, 0).
    """
    n_classes = int(classes.max()) + 1
    coeffs = np.tile([1.0, 0.0], (n_classes, 12, 1))
    for cls in range(n_classes):
        in_class = classes == cls
        for month in range(12):
            x = viirs[:, month][:, in_class].ravel()
            y = modis[:, month][:, in_class].ravel()
            ok = ~(np.isnan(x) | np.isnan(y))
            if ok.sum() < 2 or np.ptp(x[ok]) == 0:
                if ok.any():
                    coeffs[cls, month] = (1.0, float(np.mean(y[ok] - x[ok])))
                continue
            coeffs[cls, month] = np.polyfit(x[ok], y[ok], 1)
    return coeffs


def apply_correction(viirs: np.ndarray, classes: np.ndarray, coeffs: np.ndarray) -> np.ndarray:
    """Correct one year of VIIRS NDVI, (month, height, width), to agree with MODIS."""
    slope = coeffs[classes, :, 0].transpose(2, 0, 1)
    intercept = coeffs[classes, :, 1].transpose(2, 0, 1)
    return slope * viirs + intercept


def quality_weight(good_share: np.ndarray) -> np.ndarray:
    """Training weight from the share of good (not marginal) pixels behind a value."""
    return 0.5 + 0.5 * good_share
