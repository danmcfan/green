# PMTiles raster maps, stored in GitHub Releases rather than git

Each map is a raster PMTiles file, drawn in the browser with MapLibre. This replaces smart-farm's Mapbox-hosted tilesets, which needed a Mapbox account and an upload by hand for each tileset. The PMTiles files are not committed: they total hundreds of MB, and git would keep every version forever. The pipeline runs in the `Pipeline` GitHub Actions workflow, started by hand, and uploads its output to a GitHub Release; it can still run on a developer's machine the same way. Then it starts the Pages deploy job on `main`, which downloads that Release and publishes the files with the site, so the deploy itself never needs Google Earth Engine credentials.

## Considered Options

- Commit the PMTiles to git: rejected because the repo would grow without limit.
- Run the pipeline only on a developer's machine: this was the first choice, to keep the Earth Engine key out of CI. Replaced so that maps can be rebuilt without a local setup. The key is stored as a repository secret and is only used by the `Pipeline` workflow, never by Deploy. A GitHub-hosted job can run for at most 6 hours, so a run must fit in that time (see #15).
- Deploy on each published Release: rejected because a Release event runs on the tag, and the `github-pages` environment only accepts deploys from `main`.
