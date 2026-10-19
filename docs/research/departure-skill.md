# Research: do the Input layers predict the Departure?

Follows issue #26. Data: the `conus` Region, 2008–2013 (6 years), natural Land cells only, 18,428,184 rows (cell × month × year), with every Input layer including `recent_prcp`, `recent_prcp_1m`, `recent_tmax` and `recent_vp` (3523a1f, ef32d00). Script: `docs/research/scripts/departure_skill.py` (run from `backend/` with `uv run python`, reads the cached `data/conus`, no Earth Engine calls; about 1.5 hours).

## Short answer

**Weakly, yes.** On unseen years the Input layers explain about **12%** of the Departure (R² 0.12). The error falls from 0.067 NDVI (predicting no Departure) to 0.062 NDVI. That is real, not noise, but it is small. Most of the Departure is still unexplained.

## Method

- **Departure target:** Observed NDVI minus the mean Observed NDVI for the same cell and month in the *other* years (the held-out year is never in its own baseline).
- **Model:** the same GBM as `train.py`, fitted on training-row Departures (each with its own year left out of its baseline, as in `_training_departures`).
- **Baseline:** predict a Departure of 0, i.e. "this year is a usual year". R² is measured against that baseline, so R² 0 means no skill.
- Rows are weighted by Observed NDVI quality, as in training.
- Holdouts, with 200 km Spatial blocks in 5 folds (seed 0, as in `train.py`):
  - **Unseen years:** hold out each year in turn, train on the other 5 (6 tests).
  - **Unseen places:** hold out each fold of Spatial blocks, all years (5 tests).
  - **Both:** hold out one year *and* one fold, train on the other years in the other folds (30 tests).

## Results

| Holdout | Mean R² | RMSE (model) | RMSE (predict 0) | Correlation | Tests with R² > 0 |
|---|---|---|---|---|---|
| Unseen years | **0.124** | 0.0622 | 0.0667 | 0.33 | 6 of 6 |
| Unseen places | 0.222 | 0.0593 | 0.0672 | 0.45 | 5 of 5 |
| Both | **0.115** | 0.0625 | 0.0667 | 0.32 | 30 of 30 |
| Unseen years, soil + month only (control) | 0.001 | 0.0666 | 0.0667 | 0.00 | 3 of 6 |

Unseen years, by held-out year:

| 2008 | 2009 | 2010 | 2011 | 2012 | 2013 |
|---|---|---|---|---|---|
| 0.045 | 0.054 | 0.160 | 0.206 | 0.181 | 0.095 |

(These differ slightly from the issue #26 numbers, 0.051–0.167, mean 0.102, because those score `climatology_gbm` unweighted against the training-years climatology. Same conclusion.)

## Is it real?

Yes, for these reasons:

- Every one of the 6 unseen-year tests and all 30 unseen-year-and-place tests score above 0.
- The control model, with only soil and month (which do not change from year to year), scores 0.001. So the skill comes from the weather, not from the model learning where Departures tend to be large.
- The skill is largest in 2010–2012, which had large weather events (the 2011 Southern Plains drought, the 2012 Midwest drought). It is smallest in the quiet years 2008–2009.

But it is small. Even in the best year the model removes only about a tenth of the RMSE.

**Unseen places score higher (0.22) but it is the easier test.** The model has seen the same year in nearby blocks, so it can learn "this year was dry and brown here" from the neighbours. Unseen years, or both, is the honest measure of whether the weather explains the Departure: about 0.12.

## Which Input layers matter

Permutation importance on the unseen-year models (fall in R² when one Input layer is shuffled, mean over the 6 years, 100,000 rows each):

| Input layer | R² drop |
|---|---|
| `climate_tmax` | 0.47 |
| `climate_dayl` | 0.23 |
| `recent_tmax` | 0.08 |
| `recent_prcp` (3 months) | 0.06 |
| `soil_ph_0cm` | 0.06 |
| `recent_prcp_1m` | 0.04 |
| `climate_tmin` | 0.04 |
| every other layer | ≤ 0.03 |

Read these with care: the drops are bigger than the R² itself because shuffling a seasonal layer such as `tmax` or `dayl` puts summer values in winter rows, which the model has never seen. The order is the useful part. **This month's temperature leads, then recent temperature and recent rainfall.** Soil matters only as context for how a place reacts to weather. `recent_vp` and same-month `prcp` add little.

## What this means

- The model predicts NDVI for unseen places well (R² about 0.85 from `train.py`), but nearly all of that is the usual NDVI of a place and month. Only about a tenth of how unusual a year is can be predicted from the Input layers.
- Issue #26's pass rule (mean ≥ 0.10, > 0 in 5 of 6) is met, but only just. Do not present the Predicted NDVI as a forecast of droughts or green years.
- `train.log` in the repo root is from an earlier 3-year run (9,225,396 rows) and does not match the 6-year run used here.

## Possible next steps

- Add a drought index that carries water deficit over longer times (SPEI or a soil-moisture layer, e.g. 6–12 month windows). Issue #26 deferred SPEI; the importance ranking (temperature and 3-month rain lead) suggests longer memory of water balance is the most likely gain.
- Add more years (2001–2023) so the model sees more kinds of weather; 6 years is few for learning year-to-year change.

## Adding 6- and 12-month water balance (issue #41)

**It does not help.** Two new Input layers, `recent_water_6m` and `recent_water_12m`: rainfall minus potential evapotranspiration (Hargreaves' radiation form, from the Daymet `srad`, `dayl`, `tmax` and `tmin` already extracted), averaged over the previous 6 or 12 months. Built from the cached climate, so no new Earth Engine extract was needed. SPEI (`CSIC/SPEI/2_9`) is 0.5°, far coarser than the 4 km grid; TerraClimate `def`/`soil` is about 4 km but would need a new extract for a similar signal.

Script: `docs/research/scripts/water_balance_skill.py`, unseen years only, on a fixed-seed sample of 8% of natural cells (all their years kept, 1,474,200 rows; about 7 minutes). Same method as above.

| Unseen year | 2008 | 2009 | 2010 | 2011 | 2012 | 2013 | Mean R² |
|---|---|---|---|---|---|---|---|
| Without water balance | 0.049 | 0.050 | 0.158 | 0.194 | 0.177 | 0.093 | **0.120** |
| With 6 and 12 months | 0.049 | 0.036 | 0.161 | 0.209 | 0.171 | 0.106 | **0.122** |
| With 6 months only | 0.048 | 0.047 | 0.170 | 0.205 | 0.167 | 0.097 | **0.122** |

The gain, +0.002 R², is smaller than the year-to-year swings either way (2009 −0.014, 2011 +0.015), so it is noise. The sample's baseline (0.120) matches the full-data 0.124. The 3-month rainfall and temperature layers already carry what this water balance knows; longer memory of water is not what the model is missing. More years (2001–2023) remain the more likely gain.

The two layers were then removed from the model: they added inputs and code for no gain in skill. The script above is the record of this result; it needs the layers, so run it at commit cd82cb3.
