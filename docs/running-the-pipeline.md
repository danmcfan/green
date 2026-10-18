# Running the pipeline

## Without credentials

This runs every step on a small region with synthetic data and writes PMTiles to `tiles/small/`:

```sh
task pipeline:fixture
```

## Against Earth Engine

Real runs read from Google Earth Engine. Put a service-account key in `keys/` (ignored by git) and set `GEE_EMAIL` and `GEE_KEY_FILE` in `.env`. Then:

```sh
task pipeline -- run --region small --start 2010 --end 2013   # extract → train → predict → crop effect → tiles
task pipeline -- publish --region small --tag tiles-2026-10   # upload the PMTiles to a GitHub Release and deploy it
```

Each step can also run on its own (`extract`, `train`, `predict`, `crops`, `tiles`). Use `--region conus` for the whole country. Output goes to `data/`, `models/` and `tiles/`, all ignored by git. Any range of years works.

To see your own output on the local map, run `task tiles:local` (or `task tiles:local REGION=conus`) after the pipeline. It links `tiles/<region>/` into `frontend/public/tiles/` under the same names the Release uses, with an `index.json` listing them.

## Logs

Each step writes its log to `<step>.log` at the repo root (`run.log`, `train.log`, …) as well as to the terminal, and each run replaces that file. `--logs-dir` puts the logs somewhere else. To follow a run, watch its log from another terminal. The view shows each download's progress and the latest warnings and errors:

```sh
task pipeline -- run --region conus --start 2008 --end 2013
task pipeline:watch            # or LOG=other.log
```

## Earth Engine limits

If Earth Engine refuses requests for its concurrency limit, as it does once a noncommercial project has used its monthly EECU-hours and is in [Restricted Mode](https://developers.google.com/earth-engine/guides/noncommercial_tiers#restricted_mode), extract halves the requests it sends at once, down to one, and carries on more slowly. `--workers 1` starts it there. The EECU-hours reset on the first of each month at midnight Pacific time. The project's tier is on the [Manage tier](https://console.cloud.google.com/earth-engine/configuration/manage-tier) page and its past usage in Cloud Monitoring's Metrics Explorer.

## Saved downloads

Extract saves each download under `data/<region>/` and reuses it on the next run, so a run that fails part way starts again where it stopped. To fetch data again, delete it:

```sh
task pipeline:clear REGION=conus                                 # every saved download
task pipeline:clear REGION=conus -- --only land_cover ndvi/2012  # some files or folders
```

A run that includes a year after 2026 first fits the VIIRS correction once per region on every year from 2012–2026, whatever years it covers, and saves it in `data/<region>/ndvi_correction.npz` for later runs. It is fitted again if the saved one came from another source (`--source`).

## Size limits

`tiles` and `publish` fail if the PMTiles would not fit within the GitHub Release or Pages limits (file count, largest file, total size), which are set in `backend/src/green/limits.py`.

## Deployment

The `Deploy` workflow builds the site, downloads a Release's `*.pmtiles` into it (the latest one, unless it is given a tag), writes `tiles/index.json` so the map knows which years and months exist, and publishes it to GitHub Pages. It runs on every push to `main`, after each `publish`, and by hand. To enable it, set **Settings → Pages → Source** to **GitHub Actions**.
