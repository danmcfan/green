# Research: valid Observed NDVI target and honest model evaluation

Issue #3. Constraints from `docs/adr/0003-conus-4km-annual-grid.md`: CONUS, 4 km grid, one growing-season median Observed NDVI per year, 2001 to last full year, built in Google Earth Engine (GEE).

> Verification note: live web fetches failed (network errors) while writing this. Asset IDs, band names, scale factors and QA bits below come from the cited GEE catalog pages and product user guides as known to the author. **Check each link before the code depends on it.**

## 1. Source dataset

| Option | 2001 coverage | Notes |
|---|---|---|
| MODIS Terra `MODIS/061/MOD13A1` (16-day VI, 500 m) | Yes (from 2000-02-18) | NDVI already computed, BRDF-reduced compositing (CV-MVC), consistent sensor through the whole record. Best fit. |
| `MODIS/061/MOD13Q1` (250 m) | Yes | Same algorithm, finer grid. Unnecessary for 4 km; 4x the pixels to reduce. |
| `MODIS/061/MOD09GA` daily SR, NDVI computed yourself | Yes | More work: you must handle clouds, view angle and BRDF yourself. No benefit at 4 km. |
| Landsat 5/7/8/9 C02 L2 merged | Yes (L5 + L7) | 30 m, but sensors differ (TM/ETM+ vs OLI), so you need cross-sensor harmonisation (Roy et al. 2016). L7 SLC-off gaps after 2003-05, 16-day revisit gives few clear scenes per season, 2012 gap (L5 ended Nov 2011, L8 from Apr 2013, only gappy L7). Much more compute for no gain at 4 km. |
| AVHRR / NOAA CDR NDVI (`NOAA/CDR/AVHRR/NDVI/V5`) | Yes | ~5 km, older sensors with drift. Weaker than MODIS. |
| VIIRS `NOAA/VIIRS/001/VNP13A1` | From 2012 only | Could later take over from MODIS, but cannot start in 2001. |

**Recommendation: `MODIS/061/MOD13A1`, band `NDVI`, scale factor 0.0001 (valid range -2000..10000).** Terra only. Aqua (`MYD13A1`) starts in mid-2002, so adding it would change the input partway through the record.
Note that Terra is drifting in orbit and is near end of life. Collection 6.1 is current. If Terra data stops, the latest years may need a VIIRS bridge (an open question).

Sources: GEE catalog https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD13A1 ; MODIS VI User Guide C6.1 (Didan et al.), https://lpdaac.usgs.gov/documents/621/MOD13_User_Guide_V61.pdf ; Roy et al. 2016, *Remote Sens. Environ.* 185:57-70 (Landsat OLI/ETM+ harmonisation).

## 2. Masking recipe (MOD13A1)

- Use band `SummaryQA` (0 = good, 1 = marginal, 2 = snow/ice, 3 = cloudy). **Keep 0, and optionally keep 1.** Keeping only 0 leaves gaps in humid areas such as the Southeast and Pacific Northwest. Recommended: keep 0 and 1, then rely on the median.
- Optional stricter mask from `DetailedQA`: bits 0-1 VI quality (00 good, 01 check other QA), bits 2-5 usefulness, bit 8 adjacent cloud, bit 10 mixed clouds, bit 14 possible snow/ice, bit 15 possible shadow. See User Guide Table 5.
- Multiply by 0.0001 after masking.
- Record a per-pixel count of valid composites. Mask any pixel-year with fewer than about 3 valid composites in the season.
- Not needed for MODIS: if Landsat were used, C02 L2 SR is `DN * 0.0000275 - 0.2`, and the QA_PIXEL bits are 1 dilated cloud, 3 cloud, 4 shadow, 5 snow (GEE `LANDSAT/LC08/C02/T1_L2` page).

## 3. Growing season, composite and aggregation to 4 km

- **Fixed window, May 1 to Sep 30, for every pixel.** A per-pixel phenology window such as `MODIS/061/MCD12Q2` would itself depend on climate. That leaks part of the target into how the target is defined, and its gaps make it noisy. A fixed window is simple, reproducible and easy to explain. Caveat: winter-wet areas (California, desert Southwest monsoon) peak at other times. This is acceptable because the model's job is "May-Sep greenness". State this in the layer definition.
- Composite: `ee.Reducer.median()` over the masked 16-day composites whose start date falls in the window (about 9-10 images).
- Order of operations: first take the median at 500 m, then aggregate. Use `reduceResolution(ee.Reducer.mean(), maxPixels≈128)` followed by `reproject` to the target grid. Mask a 4 km cell when less than about 50% of its 500 m pixels are valid. Get the fraction with a `count`, or with mean of the mask.
- Target grid: **use the same grid as the climate Input layers**, so there is no second resampling. gridMET (`IDAHO_EPSCOR/GRIDMET`) is 1/24 degree (~4 km) in EPSG:4326. PRISM (`OREGONSTATE/PRISM/AN81m`) uses the same 1/24 degree (2.5 arc-min) grid. Choosing EPSG:4326 at 1/24 degree, aligned to PRISM's extent and crs transform, lines up all three. Soil layers (e.g. SoilGrids or POLARIS) are then mean-aggregated onto that grid.

Sources: GEE `reduceResolution` guide https://developers.google.com/earth-engine/guides/resample ; gridMET (Abatzoglou 2013, *Int. J. Climatol.* 33:121-131) ; PRISM catalog https://developers.google.com/earth-engine/datasets/catalog/OREGONSTATE_PRISM_AN81m .

## 4. Masking non-vegetated and managed land

- Soil and climate cannot see irrigation, fertilizer, crop choice or urban surfaces. If these pixels are kept, the model learns noise that it cannot explain, and the reported error mixes "natural" error with "management" error.
- Recommended mask: **exclude water, developed, barren and cultivated crops; keep forest, shrub, grass and pasture/hay** (pasture is managed too, which is an open question). Build one static mask from the land-cover data and apply it to every year. A 4 km cell is kept only when at least about 75% of its area is in the kept classes.
- Land-cover options:
  - NLCD (`USGS/NLCD_RELEASES/2019_REL/NLCD`, epochs 2001-2019; newer Annual NLCD `projects/sat-io/...`/USGS Annual NLCD 1985-2023). 30 m, CONUS. Classes 11/12 water and ice, 21-24 developed, 31 barren, 81 pasture, 82 cultivated crops. Most accurate for CONUS.
  - MODIS `MODIS/061/MCD12Q1` LC_Type1 (IGBP), 500 m, annual 2001 onward. Classes 12 croplands, 14 cropland/natural mosaic, 13 urban, 16 barren, 17 water. Simpler to use, but less accurate.
  - USDA Cropland Data Layer `USDA/NASS/CDL` (CONUS-wide from 2008), for a crop mask that changes by year. Only if the human decides to model cropland separately.
- Recommendation: NLCD 2001 plus the latest epoch. Combine them with a union of "ever non-natural" so the mask does not change between years.

Sources: NLCD class legend https://www.mrlc.gov/data/legends/national-land-cover-database-class-legend-and-description ; MCD12Q1 User Guide (Sulla-Menashe & Friedl 2018).

## 5. Honest evaluation

- NDVI and climate are strongly spatially autocorrelated, so random K-fold CV inflates the scores (Roberts et al. 2017, *Ecography* 40:913-929; Ploton et al. 2020, *Nat. Commun.* 11:4540). Meyer & Pebesma 2021 (*Methods Ecol. Evol.*) also show that models do not transfer to unseen environments.
- **Spatial block CV**: blocks at least as large as the range of residual autocorrelation. Estimate the range from a variogram of the residuals of a simple model; for CONUS climate-driven NDVI, expect a few hundred km. Start with 200 km square blocks, assign blocks to 5 folds at random, and report how sensitive the scores are to 100 and 400 km blocks. Every year of a cell must fall in the same fold.
- **Temporal holdout**: keep the last 3 full years apart as a final test set. Do not use them for tuning.
- **Combined (strictest)**: test on held-out blocks × held-out years. This answers "new place, new year". Report three numbers: spatial-only, temporal-only and combined.
- Fit preprocessing (scaler, imputer, feature selection) **inside each training fold only**, e.g. a sklearn `Pipeline`. Save the final fitted pipeline (scaler plus model) with joblib, together with its training years, block size and seed.
- Tune hyperparameters with nested CV, or with blocks inside the training set only.

## 6. Baselines and metrics

- Global mean of the training target. This is the floor, and it defines R² = 0.
- Per-pixel climatology (mean Observed NDVI for that cell in the training years). Valid **only for the temporal holdout**, because unseen blocks have no history. It is a very strong baseline for year-to-year prediction. Also report "climatology + anomaly" skill, i.e. R² of the year-to-year anomalies.
- Ridge regression on standardised Input layers.
- Gradient boosting (LightGBM / sklearn `HistGradientBoostingRegressor`). This is the likely final model.
- Metrics: RMSE and MAE in NDVI units, and R². Report them per CV scheme as mean ± std over folds, with every baseline in the same table. Add RMSE by land-cover class and by ecoregion, and a map of the residuals.

## Open questions for a human

1. Keep or mask pasture/hay (NLCD 81)? Keep or mask cropland (82)? The recommendation is to mask 82.
2. Terra end of life: accept the record ending at the last Terra year, or bridge with VIIRS VNP13A1 for the latest years?
3. Is a fixed May-Sep window acceptable for winter-wet regions?
4. Keep SummaryQA = 1 (marginal) or not?
