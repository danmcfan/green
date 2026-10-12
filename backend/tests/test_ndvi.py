import numpy as np
import pytest

from green.ndvi import apply_correction, fit_correction, quality_weight


def test_correction_recovers_a_linear_fit_per_class_and_month():
    rng = np.random.default_rng(0)
    modis = rng.uniform(0.1, 0.9, (2, 12, 5, 5))  # two overlap years
    classes = np.zeros((5, 5), int)
    classes[:, 3:] = 1
    viirs = np.where(classes == 0, 0.9 * modis + 0.05, 1.1 * modis - 0.02)
    viirs[:, 4] -= 0.1  # May differs from the other months

    coeffs = fit_correction(modis, viirs, classes)
    corrected = apply_correction(viirs[0], classes, coeffs)
    assert corrected == pytest.approx(modis[0])


def test_correction_ignores_missing_cells_and_keeps_them_missing():
    modis = np.full((1, 12, 2, 2), 0.5)
    viirs = np.full((1, 12, 2, 2), 0.6)
    modis[0, :, 0, 0] = np.nan
    viirs[0, 0, 1, 1] = np.nan
    coeffs = fit_correction(modis, viirs, np.zeros((2, 2), int))
    corrected = apply_correction(viirs[0], np.zeros((2, 2), int), coeffs)
    assert np.isnan(corrected[0, 1, 1])
    assert corrected[1, 1, 1] == pytest.approx(0.5)


def test_class_without_overlap_data_is_left_unchanged():
    coeffs = fit_correction(
        np.full((1, 12, 1, 1), np.nan), np.ones((1, 12, 1, 1)), np.zeros((1, 1), int)
    )
    assert apply_correction(
        np.full((12, 1, 1), 0.3), np.zeros((1, 1), int), coeffs
    ) == pytest.approx(np.full((12, 1, 1), 0.3))


def test_good_quality_counts_for_more_than_marginal():
    assert quality_weight(np.array([1.0, 0.0, 0.5])).tolist() == [1.0, 0.5, 0.75]
