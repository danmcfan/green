# Observed NDVI from MODIS while Terra has data

Observed NDVI comes from MODIS Terra (`MODIS/061/MOD13A1`) for every year up to 2026, the last year Terra collects (ADR 0005). Only years after that come from VIIRS, corrected to MODIS as ADR 0005 describes. This replaces ADR 0005's switch to VIIRS in 2012.

On CONUS a VIIRS year takes about 35 minutes to fetch, against about 10 for MODIS. The switch in 2012 also made any run that reached 2012 fit the VIIRS correction first, which means fetching 30 years of NDVI (about 11 hours). With MODIS up to 2026, no run needs VIIRS until we add 2027, and no Observed NDVI before then carries the correction's error.

## Consequences

- Each year still comes from one satellite only, and a run's Observed NDVI does not depend on which years it covers.
- The first run that includes 2027 fits the VIIRS correction on 2012–2026, as before. Saved correction years are kept, so the MODIS half may already be there.
- Observed NDVI saved for 2012 or later by an earlier run is VIIRS. Clear it (`green clear --only ndvi/<year>`) before training on it with MODIS years.

## Considered Options

- Keep VIIRS from 2012: rejected because it costs about 11 hours per region and adds the correction's error for no gain while Terra still has data.
