"""Unseen-year Departure R², with and without the recent water-balance Input layers (issue #41).

Same method as departure_skill.py, on a fixed-seed sample of whole cells (so every sampled
cell keeps all its years for the Departure baseline). Run from backend/:
    uv run python ../docs/research/scripts/water_balance_skill.py out.json [cell_share]
"""

import importlib
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

from green.store import Store

T = importlib.import_module("green.train")
logging.basicConfig(level=logging.INFO)
share = float(sys.argv[2]) if len(sys.argv) > 2 else 0.08
rows = T.build_rows(Store(Path(__file__).resolve().parents[3] / "data" / "conus"))
cells = np.unique(rows.row * 100_000 + rows.col)
picked = np.random.default_rng(0).choice(cells, int(len(cells) * share), replace=False)
rows = rows.take(np.isin(rows.row * 100_000 + rows.col, picked))
years = sorted(set(rows.year.tolist()))
dep_all = T._training_departures(rows)
print("rows", len(rows.y), "cells", len(picked), "years", years, flush=True)
WATER = [T.INPUT_LAYERS.index(n) for n in ("recent_water_6m", "recent_water_12m")]
VARIANTS = {
    "without": [i for i in range(len(T.INPUT_LAYERS)) if i not in WATER],
    "with": list(range(len(T.INPUT_LAYERS))),
    "with_6m_only": [i for i in range(len(T.INPUT_LAYERS)) if i != WATER[1]],
}


def score(target, pred, w):
    ok = ~np.isnan(target)
    t, p, w = target[ok], pred[ok], w[ok]
    sse, sst = (w * (p - t) ** 2).sum(), (w * t**2).sum()
    return {
        "r2": float(1 - sse / sst),
        "rmse": float(np.sqrt(sse / w.sum())),
        "rmse_zero": float(np.sqrt(sst / w.sum())),
    }


out = {v: {} for v in VARIANTS}
for y in years:
    tr, te = rows.take(rows.year != y), rows.take(rows.year == y)
    d = T._training_departures(tr)
    keep = ~np.isnan(d)
    for name, cols in VARIANTS.items():
        t0 = time.time()
        r = T.Rows(**{**vars(tr), "y": d, "x": tr.x[:, cols]}).take(keep)
        p = T._fit(T.gbm(0), r).predict(te.x[:, cols])
        out[name][y] = score(dep_all[rows.year == y], p, te.weight)
        print(name, y, out[name][y], round(time.time() - t0), flush=True)
for name in VARIANTS:
    v = out[name].values()
    out[name + "_mean"] = {
        m: float(np.mean([x[m] for x in v])) for m in ("r2", "rmse", "rmse_zero")
    }
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k.endswith("_mean")}, indent=1))
