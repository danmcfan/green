"""The CONUS 4 km grid (ADR 0003): 1/24 degree cells in EPSG:4326, aligned to PRISM."""

import math
from dataclasses import dataclass

import numpy as np

CELL = 1 / 24
CRS = "EPSG:4326"
KM_PER_DEGREE = 111.32


def _snap_down(value: float) -> float:
    # Cell edges sit at k/24 - 1/48 degrees, the PRISM / gridMET lattice.
    return math.floor(round((value + CELL / 2) / CELL, 9)) * CELL - CELL / 2


def _snap_up(value: float) -> float:
    return math.ceil(round((value + CELL / 2) / CELL, 9)) * CELL - CELL / 2


@dataclass(frozen=True)
class Grid:
    """A rectangle of cells, given by its top-left corner and size in cells."""

    x0: float
    y0: float
    width: int
    height: int

    @classmethod
    def from_bounds(cls, xmin: float, ymin: float, xmax: float, ymax: float) -> Grid:
        left, right = _snap_down(xmin), _snap_up(xmax)
        bottom, top = _snap_down(ymin), _snap_up(ymax)
        return cls(left, top, round((right - left) / CELL), round((top - bottom) / CELL))

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (
            self.x0,
            self.y0 - self.height * CELL,
            self.x0 + self.width * CELL,
            self.y0,
        )

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    def cell_centers(self) -> tuple[np.ndarray, np.ndarray]:
        """Longitude and latitude of each cell centre, as (height, width) arrays."""
        lon = self.x0 + (np.arange(self.width) + 0.5) * CELL
        lat = self.y0 - (np.arange(self.height) + 0.5) * CELL
        return np.meshgrid(lon, lat)

    def chunks(self, size: int) -> list[tuple[int, int, Grid]]:
        """Split into sub-grids of at most size × size cells, with their row and column offsets."""
        return [
            (
                row,
                col,
                Grid(
                    self.x0 + col * CELL,
                    self.y0 - row * CELL,
                    min(size, self.width - col),
                    min(size, self.height - row),
                ),
            )
            for row in range(0, self.height, size)
            for col in range(0, self.width, size)
        ]

    def ee_grid(self) -> dict:
        """The pixel grid of an Earth Engine getPixels / computePixels request."""
        return {
            "dimensions": {"width": self.width, "height": self.height},
            "affineTransform": {
                "scaleX": CELL,
                "shearX": 0,
                "translateX": self.x0,
                "shearY": 0,
                "scaleY": -CELL,
                "translateY": self.y0,
            },
            "crsCode": CRS,
        }

    def to_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "width": self.width, "height": self.height}


CONUS = Grid.from_bounds(-125.0, 24.0, -66.5, 49.9375)

REGIONS = {
    "conus": CONUS,
    # Central Iowa: farm land with natural cells next to it, for quick runs.
    "small": Grid.from_bounds(-94.0, 41.5, -93.0, 42.5),
}


def spatial_blocks(grid: Grid, block_km: float) -> np.ndarray:
    """Square blocks of about block_km, for spatial cross-validation; one id per cell."""
    lon, lat = grid.cell_centers()
    mid_lat = (grid.bounds[1] + grid.bounds[3]) / 2
    km_x = (lon - grid.x0) * KM_PER_DEGREE * math.cos(math.radians(mid_lat))
    km_y = (grid.y0 - lat) * KM_PER_DEGREE
    col = (km_x // block_km).astype(int)
    row = (km_y // block_km).astype(int)
    return row * (col.max() + 1) + col
