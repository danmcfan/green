import io

import numpy as np
from PIL import Image
from pmtiles.reader import MmapSource, Reader

from green.crops import CROP_TYPES
from green.grid import Grid
from green.layers import LayerDefinition, load_layers
from green.tiles import colorize, render_tile, tiles_covering, write_pmtiles

LAYER = LayerDefinition(
    id="observed_ndvi",
    name="Observed NDVI",
    kind="observed",
    units="NDVI",
    range=(0.0, 1.0),
    colors=("#000000", "#ff0000", "#ffffff"),
)


def test_colorize_interpolates_stops_and_clamps():
    rgba = colorize(np.array([[0.0, 0.25, 0.5, 1.0, 2.0, -1.0]]), LAYER)
    assert rgba[0, 0].tolist() == [0, 0, 0, 255]
    assert rgba[0, 1].tolist() == [128, 0, 0, 255]
    assert rgba[0, 2].tolist() == [255, 0, 0, 255]
    assert rgba[0, 3].tolist() == [255, 255, 255, 255]
    assert rgba[0, 4].tolist() == [255, 255, 255, 255]
    assert rgba[0, 5].tolist() == [0, 0, 0, 255]


def test_colorize_leaves_missing_values_transparent():
    assert colorize(np.array([[np.nan]]), LAYER)[0, 0, 3] == 0


def test_colorize_draws_each_crop_type_in_its_own_color():
    layer = load_layers()["crop_type"]
    rgba = colorize(np.arange(len(CROP_TYPES), dtype=float)[None, :], layer)
    for index, color in enumerate(layer.colors):
        hex_color = "#" + "".join(f"{c:02x}" for c in rgba[0, index, :3])
        assert hex_color == color.lower()


def test_tiles_covering_a_small_grid():
    grid = Grid.from_bounds(-94, 41.5, -93, 42.5)
    assert tiles_covering(grid, 0) == [(0, 0, 0)]
    z6 = tiles_covering(grid, 6)
    assert (6, 15, 23) in z6
    assert all(z == 6 for z, _, _ in z6)


def test_render_tile_samples_the_grid():
    grid = Grid.from_bounds(-94, 41.5, -93, 42.5)
    values = np.full(grid.shape, 1.0)
    png = render_tile(values, grid, LAYER, 6, 15, 23)
    image = np.array(Image.open(io.BytesIO(png)))
    assert image.shape == (256, 256, 4)
    assert (image[..., 3] == 255).any() and (image[..., 3] == 0).any()
    assert render_tile(values, grid, LAYER, 6, 0, 0) is None


def test_write_pmtiles_produces_a_readable_archive(tmp_path):
    grid = Grid.from_bounds(-94, 41.5, -93, 42.5)
    path = tmp_path / "ndvi.pmtiles"
    write_pmtiles(path, np.full(grid.shape, 0.5), grid, LAYER, max_zoom=6)
    with open(path, "rb") as f:
        reader = Reader(MmapSource(f))
        header = reader.header()
        assert header["max_zoom"] == 6
        assert reader.get(6, 15, 23) is not None
        assert reader.metadata()["layer"] == "observed_ndvi"
