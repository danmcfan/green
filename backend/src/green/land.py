"""Land cells: the Region is a rectangle, so it also covers Canada, Mexico and sea."""

import logging
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import shapefile
import shapely
from shapely.geometry import shape

from green.grid import CELL, Grid
from green.store import Store

logger = logging.getLogger(__name__)

# Census cartographic boundary states at 1:500,000. Unlike TIGER/Line legal boundaries they
# are cut to the shoreline, so coasts and the Great Lakes are water. They are in NAD83, which
# is within a metre or two of the grid's EPSG:4326 across CONUS.
STATES_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_500k.zip"
# Alaska and Hawaii; territories have state FIPS codes of 60 and up.
NOT_CONUS_FIPS = {"02", "15"}
# A cell is a Land cell when at least this share of it is land in the 48 states or DC.
LAND_SHARE = 0.5


def land_cells(store: Store) -> np.ndarray:
    """Land cells; every cell for data extracted before land was, until extract runs again."""
    if not store.path("land").exists():
        logger.warning("No saved land: using every cell. Run extract to leave out the sea")
        return np.ones(store.grid().shape, dtype=bool)
    return store.load("land")["land_share"] >= LAND_SHARE


def conus_boundary(url: str = STATES_URL) -> shapely.Geometry:
    """The 48 states and DC as one geometry."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "states.zip"
        urllib.request.urlretrieve(url, path)
        with shapefile.Reader(str(path)) as reader:
            states = [
                shape(record.shape.__geo_interface__)
                for record in reader.iterShapeRecords()
                if record.record["STATEFP"] < "60"
                and record.record["STATEFP"] not in NOT_CONUS_FIPS
            ]
    return shapely.union_all(states)


def land_share(grid: Grid, boundary: shapely.Geometry, samples: int = 4) -> np.ndarray:
    """(height, width) share of each cell inside `boundary`, from samples × samples points."""
    offsets = (np.arange(samples) + 0.5) / samples * CELL
    lon = grid.x0 + (np.arange(grid.width)[:, None] * CELL + offsets).ravel()
    lat = grid.y0 - (np.arange(grid.height)[:, None] * CELL + offsets).ravel()
    shapely.prepare(boundary)
    inside = shapely.contains_xy(boundary, *np.meshgrid(lon, lat))
    return inside.reshape(grid.height, samples, grid.width, samples).mean(axis=(1, 3))
