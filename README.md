# Green

Predicts how green the land is from soil and climate, and shows the Input layers, the Observed NDVI and the Predicted NDVI on a web map. See [GLOSSARY.md](GLOSSARY.md) for terms and [docs/adr/](docs/adr/) for the decisions behind the design.

## Layout

| Path | What |
|---|---|
| `backend/` | Python pipeline (uv, ruff, pytest): extract, train, predict, build tiles |
| `frontend/` | Static map site (Vite, React, shadcn, MapLibre, bun) |
| `layers.json` | The Layer definition file, read by both backend and frontend ([ADR 0004](docs/adr/0004-single-layer-definition-file.md)) |
| `Taskfile.yml` | Task runner for everything below |

## Setup

Install [uv](https://docs.astral.sh/uv/), [bun](https://bun.sh) and [Task](https://taskfile.dev). The Python and bun versions are pinned in `backend/.python-version` and `frontend/package.json` (`packageManager`). uv installs the right Python on its own.

```sh
task setup   # install dependencies, create .env from .env.example
task dev     # map at http://localhost:5173
```

Other tasks: `task lint`, `task test`, `task build`, `task check` (everything CI runs). `task --list` shows them all.

### Earth Engine credentials

Only the pipeline needs these; the site does not. Put a Google Earth Engine service-account key in `keys/` (ignored by git) and set `GEE_EMAIL` and `GEE_KEY_FILE` in `.env`. Never commit the key.

## Deployment

The site is static and served from GitHub Pages ([ADR 0001](docs/adr/0001-static-site-on-github-pages.md)). PMTiles are not in git: the pipeline uploads them to a GitHub Release, and the `Deploy` workflow downloads the latest Release's `*.pmtiles` into the site's `tiles/` folder before publishing ([ADR 0002](docs/adr/0002-pmtiles-published-from-github-releases.md)). It runs on every push to `main`, on each published Release, and by hand (with an optional release tag).

To enable it, set **Settings → Pages → Source** to **GitHub Actions**.
