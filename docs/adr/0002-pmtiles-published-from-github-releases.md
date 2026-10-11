# PMTiles raster maps, stored in GitHub Releases rather than git

Each map is a raster PMTiles file, drawn in the browser with MapLibre. This replaces smart-farm's Mapbox-hosted tilesets, which needed a Mapbox account and an upload by hand for each tileset. The PMTiles files are not committed: they total hundreds of MB, and git would keep every version forever. The pipeline runs on a developer's machine and uploads its output to a GitHub Release. The Pages deploy job downloads that Release and publishes the files with the site, so the deploy never needs Google Earth Engine credentials.

## Considered Options

- Commit the PMTiles to git: rejected because the repo would grow without limit.
- Run the full pipeline in CI: rejected because it needs a service-account key in CI and long runs.
