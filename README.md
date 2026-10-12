# Green

How green should this land be, given only its soil and climate?

Green trains a model to predict satellite NDVI (a measure of how green vegetation is) across the continental United States, each month from 2001 to the present, from soil and climate data alone. It then shows the inputs, the observed greenness and the prediction on a web map. Comparing the prediction with what satellites see shows where the model fails, and how much greener or less green farm land is than natural land would be.

> **Status:** early. The pipeline runs end to end against Earth Engine, so far on one small region (the Driftless Area, 2011–2012), and the map shows every layer it makes. That region has too few natural cells for the model scores to mean much yet ([#15](https://github.com/danmcfan/green/issues/15)).

## How it works

```
Earth Engine ──extract──▶ grid arrays ──train──▶ model ──predict──▶ Predicted NDVI ──tiles──▶ PMTiles ──▶ GitHub Release ──▶ map on GitHub Pages
```

- **Grid:** the continental US at 4 km (1/24°, lined up with PRISM), one value per month ([ADR 0003](docs/adr/0003-conus-4km-monthly-grid.md)).
- **Input layers:** soil from OpenLandMap (bulk density, clay, organic carbon, pH, sand, water content, at 0 and 30 cm), and monthly climate from Daymet (precipitation, temperature, radiation, vapor pressure, snow, day length).
- **Observed NDVI:** MODIS Terra for 2001–2011, then VIIRS from 2012, with VIIRS corrected to match MODIS by a fit for each land cover class and month ([ADR 0005](docs/adr/0005-modis-then-viirs-observed-ndvi.md)).
- **Model:** gradient boosting, trained on natural land only (forest, shrub, grass, wetland), with pixel quality as a training weight. Scores are reported for unseen places (spatial blocks), unseen years, and both together, against simple baselines. Random cross-validation would overstate the scores ([research](docs/research/ndvi-target-and-evaluation.md)).
- **Crop effect:** the natural-land model is run on farm land. Observed minus Predicted NDVI is the Crop effect for 9 crop groups from the USDA Cropland Data Layer (2008 on). Next to it, the map shows the Error next to farm land: the model's error on natural land beside farm land, for each spatial block ([ADR 0006](docs/adr/0006-crop-effect-from-natural-cover-model.md)).
- **Delivery:** every map is computed ahead of time as raster PMTiles. The site is static and needs no server ([ADR 0001](docs/adr/0001-static-site-on-github-pages.md), [ADR 0002](docs/adr/0002-pmtiles-published-from-github-releases.md)).

Terms such as Input layer, Observed NDVI and Crop effect have exact meanings, defined in [GLOSSARY.md](GLOSSARY.md).

## Layout

| Path | What |
|---|---|
| `backend/` | Python pipeline (uv, ruff, pytest, scikit-learn, Earth Engine API) |
| `frontend/` | Static map site (Vite, React, shadcn, MapLibre, bun) |
| `layers.json` | The Layer definition file (id, units, range, colors, and category names for Crop type), read by both backend and frontend ([ADR 0004](docs/adr/0004-single-layer-definition-file.md)) |
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
task pipeline -- publish --region small --tag tiles-2026-10   # upload the PMTiles to a GitHub Release
```

Each step can also run on its own (`extract`, `train`, `predict`, `crops`, `tiles`). Use `--region conus` for the whole country. Output goes to `data/`, `models/` and `tiles/`, all ignored by git. A year range that includes VIIRS years (2012 on) must include at least one year from 2012–2026, where the VIIRS correction is fitted.

## Deployment

The `Deploy` workflow builds the site, downloads the latest Release's `*.pmtiles` into it, writes `tiles/index.json` so the map knows which years and months exist, and publishes it to GitHub Pages. It runs on every push to `main`, on each published Release, and by hand. To enable it, set **Settings → Pages → Source** to **GitHub Actions**.
