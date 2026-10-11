"""Command line for the pipeline: `green run --region small --source synthetic` runs it all."""

import argparse
import json
import logging
from pathlib import Path

from green import pipeline
from green.grid import REGIONS
from green.layers import LAYERS_FILE
from green.store import Store
from green.tiles import MAX_ZOOM
from green.train import train

ROOT = LAYERS_FILE.parent


def _source(name: str, workers: int):
    if name == "synthetic":
        from green.sources import SyntheticSource

        return SyntheticSource()
    from green.gee import EarthEngineSource, initialize

    initialize()
    return EarthEngineSource(workers)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="green", description=__doc__)
    parser.add_argument(
        "step", choices=["run", "extract", "train", "predict", "crops", "tiles", "publish"]
    )
    parser.add_argument("--region", choices=sorted(REGIONS), default="small")
    parser.add_argument("--source", choices=["gee", "synthetic"], default="gee")
    parser.add_argument("--start", type=int, default=2011, help="first year")
    parser.add_argument("--end", type=int, default=2012, help="last year")
    parser.add_argument("--block-km", type=float, default=200, help="spatial CV block size")
    parser.add_argument("--max-zoom", type=int, default=MAX_ZOOM)
    parser.add_argument("--workers", type=int, default=10, help="parallel Earth Engine requests")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--models-dir", type=Path, default=ROOT / "models")
    parser.add_argument("--tiles-dir", type=Path, default=ROOT / "tiles")
    parser.add_argument("--tag", help="GitHub Release tag for publish")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    store = Store(args.data_dir / args.region)
    model_path = args.models_dir / args.region / "model.joblib"
    tiles_dir = args.tiles_dir / args.region
    years = list(range(args.start, args.end + 1))

    match args.step:
        case "run":
            store.save_grid(REGIONS[args.region])
            source = _source(args.source, args.workers)
            pipeline.run(
                source,
                store.root,
                model_path,
                tiles_dir,
                years,
                args.block_km,
                max_zoom=args.max_zoom,
            )
        case "extract":
            store.save_grid(REGIONS[args.region])
            pipeline.extract(_source(args.source, args.workers), store, years)
        case "train":
            print(json.dumps(train(store, model_path, block_km=args.block_km), indent=2))
        case "predict":
            pipeline.predict(store, model_path)
        case "crops":
            print(json.dumps(pipeline.crop_effects(store), indent=2))
        case "tiles":
            pipeline.tiles(store, tiles_dir, max_zoom=args.max_zoom)
        case "publish":
            if not args.tag:
                parser.error("publish needs --tag")
            pipeline.publish(tiles_dir, args.tag)
