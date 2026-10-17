import numpy as np
from shapely.geometry import box

from green.grid import CELL, Grid
from green.land import land_share


def test_land_share_is_the_part_of_each_cell_inside_the_boundary():
    grid = Grid(0.0, 2 * CELL, 2, 2)
    # Land covers the whole left column and the left half of the top-right cell.
    land = box(0, 0, CELL, 2 * CELL).union(box(CELL, CELL, 1.5 * CELL, 2 * CELL))
    np.testing.assert_allclose(land_share(grid, land), [[1, 0.5], [1, 0]])


def test_land_share_is_zero_for_a_grid_away_from_the_boundary():
    assert land_share(Grid(10.0, 10.0, 3, 2), box(0, 0, 1, 1)).sum() == 0
