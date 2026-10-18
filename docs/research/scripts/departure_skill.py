import json, logging, sys, time
from pathlib import Path
import numpy as np
from sklearn.inspection import permutation_importance
from green.store import Store
from green.grid import spatial_blocks
import importlib; T = importlib.import_module("green.train")

logging.basicConfig(level=logging.INFO)
store = Store(Path("/Users/dobrien/code/green/data/conus"))
rows = T.build_rows(store)
years = sorted(set(rows.year.tolist()))
blocks = spatial_blocks(store.grid(), 200)
cf = T.assign_folds(blocks.ravel(), 5, 0).reshape(blocks.shape)
folds = cf[rows.row, rows.col]
dep_all = T._training_departures(rows)  # own-year-out over all years
print("rows", len(rows.y), "years", years, flush=True)
STATIC = [i for i, n in enumerate(T.INPUT_LAYERS) if n not in T.CLIMATE_LAYERS and n not in T.RECENT_LAYERS]

def score(target, pred, w):
    ok = ~np.isnan(target)
    t, p, w = target[ok], pred[ok], w[ok]
    sse = (w * (p - t) ** 2).sum(); sst = (w * t ** 2).sum()
    return {"r2": float(1 - sse / sst), "rmse": float(np.sqrt(sse / w.sum())),
            "rmse_zero": float(np.sqrt(sst / w.sum())), "corr": float(np.corrcoef(t, p)[0, 1]), "n": int(ok.sum())}

def fit_dep(train, cols=None):
    d = T._training_departures(train); keep = ~np.isnan(d)
    r = T.Rows(**{**vars(train), "y": d}).take(keep)
    if cols is not None: r = T.Rows(**{**vars(r), "x": r.x[:, cols]})
    return T._fit(T.gbm(0), r)

out = {"temporal": {}, "temporal_static_only": {}, "spatial": {}, "combined": {}}
imp = []
rng = np.random.default_rng(0)
for y in years:
    t0 = time.time()
    tr, te = rows.take(rows.year != y), rows.take(rows.year == y)
    m = fit_dep(tr)
    p = m.predict(te.x); tgt = dep_all[rows.year == y]
    out["temporal"][y] = score(tgt, p, te.weight)
    ms = fit_dep(tr, STATIC)
    out["temporal_static_only"][y] = score(tgt, ms.predict(te.x[:, STATIC]), te.weight)
    ok = np.flatnonzero(~np.isnan(tgt)); s = rng.choice(ok, 100_000, replace=False)
    pi = permutation_importance(m, te.x[s], tgt[s], n_repeats=3, random_state=0, scoring="r2")
    imp.append(pi.importances_mean)
    print("T", y, out["temporal"][y], out["temporal_static_only"][y]["r2"], time.time() - t0, flush=True)
    for k in range(5):
        trc = rows.take((rows.year != y) & (folds != k)); sel = (rows.year == y) & (folds == k)
        if not sel.any(): continue
        mc = fit_dep(trc)
        out["combined"][f"{y}-{k}"] = score(dep_all[sel], mc.predict(rows.x[sel]), rows.weight[sel])
        print("C", y, k, out["combined"][f"{y}-{k}"], flush=True)
for k in range(5):
    tr = rows.take(folds != k); sel = folds == k
    out["spatial"][k] = score(dep_all[sel], fit_dep(tr).predict(rows.x[sel]), rows.weight[sel])
    print("S", k, out["spatial"][k], flush=True)
out["importance_r2_drop"] = dict(sorted(zip(T.INPUT_LAYERS, np.mean(imp, 0).round(4).tolist()), key=lambda kv: -kv[1]))
for key in ("temporal", "temporal_static_only", "spatial", "combined"):
    v = out[key].values()
    out[key + "_mean"] = {m: float(np.mean([x[m] for x in v])) for m in ("r2", "rmse", "rmse_zero", "corr")}
    out[key + "_above_zero"] = sum(x["r2"] > 0 for x in v)
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k.endswith(("_mean", "_above_zero")) or k.startswith("imp")}, indent=1))
