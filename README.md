# Green

How green should this land be, given only its soil and climate?

Green trains a model to predict satellite NDVI (a measure of how green vegetation is) across the continental United States, each month from 2001 to the present, from soil and climate data alone. It then shows the inputs, the observed greenness and the prediction on a web map. Comparing the prediction with what satellites see shows where the model fails, and how much greener or less green farm land is than natural land would be.

> **Status:** early. The pipeline runs end to end against Earth Engine, so far on one small region (the Driftless Area, 2011–2012), and the map shows every layer it makes. That region has too few natural cells for the model scores to mean much yet ([#15](https://github.com/danmcfan/green/issues/15)).

## How it works

```
Earth Engine ──extract──▶ grid arrays ──train──▶ model ──predict──▶ Predicted NDVI ──tiles──▶ PMTiles ──▶ GitHub Release ──▶ map on GitHub Pages
```

- **Grid:** the continental US at 4 km (1/24°, lined up with PRISM), one value per month ([ADR 0003](docs/adr/0003-conus-4km-monthly-grid.md)). A Region is a rectangle, so cells less than half US land (by the Census 1:500,000 state boundaries, cut to the shoreline) are left out of training, predictions and the map.
- **Input layers:** soil from OpenLandMap (bulk density, clay, organic carbon, pH, sand, water content, at 0 and 30 cm), and monthly climate from Daymet (precipitation, temperature, radiation, vapor pressure, snow, day length), plus the mean precipitation over the previous three months.
- **Observed NDVI:** MODIS Terra for every year up to 2026, while Terra still collects ([ADR 0007](docs/adr/0007-modis-while-terra-has-data.md)). Years after that will come from VIIRS, corrected to match MODIS by a fit for each land cover class and month ([ADR 0005](docs/adr/0005-modis-then-viirs-observed-ndvi.md)).
- **Model:** gradient boosting, trained on natural land only (forest, shrub, grass, wetland), with pixel quality as a training weight. Scores are reported for unseen places (spatial blocks), unseen years, and both together, against simple baselines. Random cross-validation would overstate the scores ([research](docs/research/ndvi-target-and-evaluation.md)).
- **Crop effect:** the natural-land model is run on farm land: cells whose main NLCD land cover class is farm (pasture/hay or cultivated crops). Observed minus Predicted NDVI there is the Crop effect. Next to it, the map shows the Error next to farm land: the model's error on natural land beside farm land, for each spatial block, the largest of its errors on unseen places, unseen years and both ([ADR 0006](docs/adr/0006-crop-effect-from-natural-cover-model.md)).
- **Delivery:** every map is computed ahead of time as raster PMTiles. The site is static and needs no server ([ADR 0001](docs/adr/0001-static-site-on-github-pages.md), [ADR 0002](docs/adr/0002-pmtiles-published-from-github-releases.md)).

Terms such as Input layer, Observed NDVI and Crop effect have exact meanings, defined in [GLOSSARY.md](GLOSSARY.md).

## Layout

| Path | What |
|---|---|
| `backend/` | Python pipeline (uv, ruff, pytest, scikit-learn, Earth Engine API) |
| `frontend/` | Static map site (Vite, React, shadcn, MapLibre, bun) |
| `layers.json` | The Layer definition file (id, units, range and colors), read by both backend and frontend ([ADR 0004](docs/adr/0004-single-layer-definition-file.md)) |
| `docs/` | Decision records (`adr/`) and research notes |
| `Taskfile.yml` | Task runner for everything below |

## Setup

Install [uv](https://docs.astral.sh/uv/), [bun](https://bun.sh) and [Task](https://taskfile.dev). uv installs the pinned Python version on its own.

```sh
task setup   # install dependencies, create .env from .env.example
task dev     # map at http://localhost:5173
task check   # lint, test and build: everything CI runs
```

To see your own pipeline output on the local map, run `task tiles:local` (or `task tiles:local REGION=conus`) after the pipeline. It links `tiles/<region>/` into `frontend/public/tiles/` under the same names the Release uses, with an `index.json` listing them.

## Running the pipeline

Try it without credentials. This runs every step on a small region with synthetic data and writes PMTiles to `tiles/small/`:

```sh
task pipeline:fixture
```

Real runs read from Google Earth Engine. Put a service-account key in `keys/` (ignored by git) and set `GEE_EMAIL` and `GEE_KEY_FILE` in `.env`. Then:

```sh
task pipeline -- run --region small --start 2010 --end 2013   # extract → train → predict → crop effect → tiles
task pipeline -- publish --region small --tag tiles-2026-10   # upload the PMTiles to a GitHub Release and deploy it
```

Each step writes its log to `<step>.log` at the repo root (`run.log`, `train.log`, …) as well as to the terminal, and each run replaces that file. `--logs-dir` puts the logs somewhere else. To follow a run, watch its log from another terminal. The view shows each download's progress and the latest warnings and errors:

```sh
task pipeline -- run --region conus --start 2008 --end 2013
task pipeline:watch            # or LOG=other.log
```

If Earth Engine refuses requests for its concurrency limit, as it does once a noncommercial project has used its monthly EECU-hours and is in [Restricted Mode](https://developers.google.com/earth-engine/guides/noncommercial_tiers#restricted_mode), extract halves the requests it sends at once, down to one, and carries on more slowly. `--workers 1` starts it there. The EECU-hours reset on the first of each month at midnight Pacific time. The project's tier is on the [Manage tier](https://console.cloud.google.com/earth-engine/configuration/manage-tier) page and its past usage in Cloud Monitoring's Metrics Explorer.

Extract saves each download under `data/<region>/` and reuses it on the next run, so a run that fails part way starts again where it stopped. To fetch data again, delete it:

```sh
task pipeline:clear REGION=conus                                 # every saved download
task pipeline:clear REGION=conus -- --only land_cover ndvi/2012  # some files or folders
```

`tiles` and `publish` fail if the PMTiles would not fit within the GitHub Release or Pages limits (file count, largest file, total size), which are set in `backend/src/green/limits.py`. Each step can also run on its own (`extract`, `train`, `predict`, `crops`, `tiles`). Use `--region conus` for the whole country. Output goes to `data/`, `models/` and `tiles/`, all ignored by git. Any range of years works. A run that includes a year after 2026 first fits the VIIRS correction once per region on every year from 2012–2026, whatever years it covers, and saves it in `data/<region>/ndvi_correction.npz` for later runs. It is fitted again if the saved one came from another source (`--source`).

## Deployment

The `Deploy` workflow builds the site, downloads a Release's `*.pmtiles` into it (the latest one, unless it is given a tag), writes `tiles/index.json` so the map knows which years and months exist, and publishes it to GitHub Pages. It runs on every push to `main`, after each `publish`, and by hand. To enable it, set **Settings → Pages → Source** to **GitHub Actions**.
