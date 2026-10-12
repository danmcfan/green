import numpy as np
import pytest

from green.grid import CELL, CONUS, Grid, spatial_blocks


def on_lattice(value):
    # Cell edges sit at k/24 - 1/48 degrees, matching PRISM's 4 km grid.
    return abs((value + CELL / 2) / CELL - round((value + CELL / 2) / CELL)) < 1e-9


def test_from_bounds_snaps_outward_to_lattice():
    grid = Grid.from_bounds(-94.01, 41.99, -93.0, 43.0)
    xmin, ymin, xmax, ymax = grid.bounds
    assert xmin <= -94.01 and ymin <= 41.99 and xmax >= -93.0 and ymax >= 43.0
    assert all(on_lattice(v) for v in grid.bounds)
    assert grid.width == round((xmax - xmin) / CELL)
    assert grid.height == round((ymax - ymin) / CELL)


def test_conus_is_about_1400_by_600_cells():
    assert 1380 < CONUS.width < 1420
    assert 600 < CONUS.height < 640


def test_cell_centers_are_half_a_cell_inside_the_edges():
    grid = Grid.from_bounds(-94, 42, -93, 43)
    lon, lat = grid.cell_centers()
    assert lon.shape == lat.shape == (grid.height, grid.width)
    assert lon[0, 0] == pytest.approx(grid.x0 + CELL / 2)
    assert lat[0, 0] == pytest.approx(grid.y0 - CELL / 2)
    assert lat[-1, 0] < lat[0, 0]


def test_chunks_tile_the_grid_exactly():
    grid = Grid.from_bounds(-94, 42, -92, 43)
    chunks = grid.chunks(10)
    assert sum(c.width * c.height for _, _, c in chunks) == grid.width * grid.height
    for row, col, chunk in chunks:
        assert chunk.x0 == pytest.approx(grid.x0 + col * CELL)
        assert chunk.y0 == pytest.approx(grid.y0 - row * CELL)
        assert chunk.width <= 10 and chunk.height <= 10


def test_ee_grid_describes_pixels_for_earth_engine():
    grid = Grid.from_bounds(-94, 42, -93, 43)
    request = grid.ee_grid()
    assert request["dimensions"] == {"width": grid.width, "height": grid.height}
    assert request["crsCode"] == "EPSG:4326"
    assert request["affineTransform"]["scaleX"] == pytest.approx(CELL)
    assert request["affineTransform"]["scaleY"] == pytest.approx(-CELL)
    assert request["affineTransform"]["translateX"] == pytest.approx(grid.x0)


def test_spatial_blocks_group_nearby_cells():
    grid = Grid.from_bounds(-100, 40, -96, 42)
    blocks = spatial_blocks(grid, block_km=200)
    assert blocks.shape == (grid.height, grid.width)
    # Neighbouring cells share a block; cells 4 degrees apart do not.
    assert blocks[0, 0] == blocks[0, 1]
    assert blocks[0, 0] != blocks[0, -1]
    # About 340 km wide by 220 km tall: 2 columns by 2 rows of 200 km blocks.
    assert len(np.unique(blocks)) == 4
