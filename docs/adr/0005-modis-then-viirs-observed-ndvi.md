# Observed NDVI from MODIS Terra to 2011, then corrected VIIRS

Terra stops collecting science data in about early 2027, so a Terra-only record cannot reach the present day. We take Observed NDVI from MODIS Terra (`MODIS/061/MOD13A1`) for 2001–2011 and from VIIRS (`NASA/VIIRS/002/VNP13A1`) from 2012, so each year comes from one satellite only. VIIRS NDVI is corrected to agree with MODIS by a linear fit for each land cover class and month, calculated on our own grid from the years where both satellites have data (2012–2026). We chose our own fit over the published spectral adjustment (Skakun et al. 2018) because it is calibrated on our grid and months, and its error can be measured.

## Considered Options

- Terra only, ending in 2026: rejected because predictions must reach the present day.
- VIIRS only from 2012: rejected because it shortens the record to 14 years.
- Sentinel-2 or Landsat: records too short, or too many cloud gaps.
