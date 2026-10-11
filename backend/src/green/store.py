"""Pipeline data on disk: one .npz per step, region and year under a data directory."""

import json
from pathlib import Path

import numpy as np

from green.grid import Grid


class Store:
    def __init__(self, root: Path):
        self.root = root

    def path(self, name: str) -> Path:
        return self.root / f"{name}.npz"

    def save(self, name: str, **arrays: np.ndarray) -> None:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **arrays)

    def load(self, name: str) -> dict[str, np.ndarray]:
        with np.load(self.path(name)) as data:
            return dict(data)

    def years(self, kind: str) -> list[int]:
        return sorted(int(p.stem) for p in (self.root / kind).glob("*.npz"))

    def save_grid(self, grid: Grid) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "grid.json").write_text(json.dumps(grid.to_dict()))

    def grid(self) -> Grid:
        return Grid(**json.loads((self.root / "grid.json").read_text()))
