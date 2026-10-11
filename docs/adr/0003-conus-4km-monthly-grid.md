# Continental US on a 4 km grid, one value per month from 2001

The model and the map cover the continental United States on a 4 km grid, with one Observed NDVI value for each month from 2001 to the present. A 4 km grid matches the detail of US gridded climate data (1 km would be 16× larger). We use the whole year, not a fixed growing season, so that NDVI can be shown at any point in the year and so that regions whose peak is outside summer (winter-wet California, the monsoon Southwest) are represented. Climate Input layers have one map per month. Soil Input layers have a single map, because soil does not change over time.

## Consequences

- A monthly series is about 12× the size of the earlier annual one. Check that the tiles still fit within the GitHub Pages and Release limits (ADR 0001, ADR 0002) before building them.
- A month's value is the median of the 500 m pixels whose observation date falls in that month. A cell with no valid observation that month stays empty; it is not filled from neighbouring months.
