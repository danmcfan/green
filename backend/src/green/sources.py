"""Where raw grid data comes from: Earth Engine in real runs, a synthetic stand-in for tests."""

from typing import Literal, Protocol

import numpy as np

from green.crops import CROP_GROUPS
from green.grid import Grid

Satellite = Literal["modis", "viirs"]

SOIL_LAYERS = tuple(
    f"soil_{name}_{depth}cm"
    for name in ("bulk_density", "clay", "organic_carbon", "ph", "sand", "water")
    for depth in (0, 30)
)
CLIMATE_LAYERS = tuple(
    f"climate_{name}" for name in ("dayl", "prcp", "srad", "swe", "tmax", "tmin", "vp")
)

# Land cover classes for the VIIRS correction; the order is the class index.
COVER_CLASSES = ("forest", "shrub", "grass", "wetland", "farm", "other")


class Source(Protocol):
    def soil(self, grid: Grid) -> dict[str, np.ndarray]:
        """One (height, width) array per soil Input layer."""
        ...

    def climate(self, grid: Grid, year: int) -> dict[str, np.ndarray]:
        """One (12, height, width) array per climate Input layer."""
        ...

    def ndvi(self, grid: Grid, year: int, satellite: Satellite) -> tuple[np.ndarray, np.ndarray]:
        """Monthly NDVI and the share of good-quality pixels behind it, each (12, h, w)."""
        ...

    def land_cover(self, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
        """Share of each cell under natural cover, and its main COVER_CLASSES index."""
        ...

    def crop_shares(self, grid: Grid, year: int) -> np.ndarray:
        """Share of each cell in each crop group, (9, height, width) in CROP_GROUPS order."""
        ...


class SyntheticSource:
    """Deterministic made-up data with a learnable link from Input layers to NDVI."""

    def __init__(self, seed: int = 0):
        self.seed = seed

    def _rng(self, *key: int) -> np.random.Generator:
        return np.random.default_rng([self.seed, *key])

    def _waves(self, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
        lon, lat = grid.cell_centers()
        return np.sin(lon * 3.1), np.cos(lat * 2.3)

    def soil(self, grid: Grid) -> dict[str, np.ndarray]:
        a, b = self._waves(grid)
        return {
            name: 50 + 20 * a * (i % 3 - 1) + 10 * b + self._rng(i).normal(0, 1, grid.shape)
            for i, name in enumerate(SOIL_LAYERS)
        }

    def climate(self, grid: Grid, year: int) -> dict[str, np.ndarray]:
        a, b = self._waves(grid)
        season = np.sin((np.arange(12) - 3) / 12 * 2 * np.pi)[:, None, None]
        rng = self._rng(year)
        wet = 80 + 40 * a + 30 * season + rng.normal(0, 10, (12, *grid.shape))
        warm = 10 + 15 * season + 3 * b + rng.normal(0, 1, (12, *grid.shape))
        full = (12, *grid.shape)
        return {
            "climate_dayl": np.broadcast_to(43000 + 8000 * season, full).copy(),
            "climate_prcp": np.maximum(wet, 0),
            "climate_srad": np.broadcast_to(250 + 120 * season, full).copy(),
            "climate_swe": np.maximum(-warm * 5, 0),
            "climate_tmax": warm + 6,
            "climate_tmin": warm - 6,
            "climate_vp": 900 + 40 * warm,
        }

    def ndvi(self, grid: Grid, year: int, satellite: Satellite) -> tuple[np.ndarray, np.ndarray]:
        soil, climate = self.soil(grid), self.climate(grid, year)
        signal = (
            0.004 * climate["climate_prcp"]
            + 0.02 * climate["climate_tmax"]
            + 0.003 * (soil["soil_clay_0cm"] - 50)
        )
        ndvi = 1 / (1 + np.exp(-(signal - 0.6) * 3))
        ndvi = ndvi + self._rng(year, 1).normal(0, 0.02, ndvi.shape)
        if satellite == "viirs":
            ndvi = 0.9 * ndvi + 0.03
        good = self._rng(year, 2).uniform(0, 1, ndvi.shape)
        ndvi[self._rng(year, 3).uniform(0, 1, ndvi.shape) < 0.03] = np.nan
        return ndvi, good

    def land_cover(self, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
        farm = self._farm_share(grid)
        cover = np.where(farm > 0.5, COVER_CLASSES.index("farm"), COVER_CLASSES.index("grass"))
        return 1 - farm, cover

    def _farm_share(self, grid: Grid) -> np.ndarray:
        # Alternating bands of farm and natural land, three cells wide.
        col = np.arange(grid.width)[None, :].repeat(grid.height, 0)
        return np.where((col // 3) % 2 == 0, 0.9, 0.05)

    def crop_shares(self, grid: Grid, year: int) -> np.ndarray:
        farm = self._farm_share(grid)
        row = np.arange(grid.height)[:, None].repeat(grid.width, 1)
        group = (row // 4 + year) % len(CROP_GROUPS)
        shares = np.zeros((len(CROP_GROUPS), *grid.shape))
        for g in range(len(CROP_GROUPS)):
            shares[g] = np.where(group == g, farm, 0)
        return shares
