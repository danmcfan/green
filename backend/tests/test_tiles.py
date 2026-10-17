import io

import numpy as np
from PIL import Image
from pmtiles.reader import MmapSource, Reader

from green.grid import Grid
from green.layers import LayerDefinition
from green.tiles import PALETTE_STEPS, colorize, render_tile, tiles_covering, write_pmtiles

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
    image = np.array(Image.open(io.BytesIO(png)).convert("RGBA"))
    assert image.shape == (256, 256, 4)
    assert (image[..., 3] == 255).any() and (image[..., 3] == 0).any()
    assert render_tile(values, grid, LAYER, 6, 0, 0) is None


def test_tiles_are_palette_pngs_within_one_step_of_the_exact_color():
    grid = Grid.from_bounds(-94, 41.5, -93, 42.5)
    values = np.random.default_rng(0).uniform(-0.2, 1.2, grid.shape)
    values[0, 0] = np.nan
    image = Image.open(io.BytesIO(render_tile(values, grid, LAYER, 6, 15, 23)))
    assert image.mode == "P"
    # Every value is drawn in the color of its nearest PALETTE_STEPS step along the ramp.
    rgba = np.array(image.convert("RGBA")).reshape(-1, 4).astype(int)
    opaque = rgba[rgba[:, 3] == 255, :3]
    exact = colorize(np.linspace(0, 1, 2001), LAYER)[:, :3].astype(int)
    nearest = np.abs(opaque[:, None] - exact[None]).sum(-1).min(axis=1)
    assert nearest.max() <= 2 * 255 // (PALETTE_STEPS - 1) + 2
    assert (rgba[:, 3] == 0).any()


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
