"""Raster PMTiles from grid arrays, colored by the Layer definition (ADR 0002, 0004)."""

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write

from green.grid import CELL, Grid
from green.layers import LayerDefinition

TILE_SIZE = 256
MIN_ZOOM = 2
# ~2.4 km pixels at the equator, finer than a 4 km cell.
MAX_ZOOM = 6
# Tiles are 8-bit palette PNGs: index 0 is missing (transparent) and the rest are this many
# evenly spaced steps along the layer's colors. Over CONUS this halves the PMTiles next to
# RGBA, which for 2008-2013 (1.10 GB) passed the Pages limit, and no step is visible.
PALETTE_STEPS = 255


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def colorize(values: np.ndarray, layer: LayerDefinition) -> np.ndarray:
    """RGBA uint8 image: values spread evenly over the color stops; missing is transparent."""
    low, high = layer.range
    stops = np.array([_hex(c) for c in layer.colors], dtype=float)
    position = np.clip((values - low) / (high - low), 0, 1) * (len(stops) - 1)
    position = np.nan_to_num(position)
    lower = np.minimum(position.astype(int), len(stops) - 2)
    t = (position - lower)[..., None]
    rgb = stops[lower] * (1 - t) + stops[lower + 1] * t
    alpha = np.where(np.isnan(values), 0, 255)[..., None]
    return np.round(np.concatenate([rgb, alpha], axis=-1)).astype(np.uint8)


def _palette_image(values: np.ndarray, layer: LayerDefinition) -> Image.Image:
    """Palette image of `values`, each drawn in its nearest PALETTE_STEPS color."""
    low, high = layer.range
    steps = colorize(np.linspace(low, high, PALETTE_STEPS), layer)
    position = np.clip((values - low) / (high - low), 0, 1) * (PALETTE_STEPS - 1)
    index = np.where(np.isnan(values), 0, np.round(np.nan_to_num(position)) + 1)
    image = Image.fromarray(index.astype(np.uint8), "P")
    image.putpalette([0, 0, 0, *steps[:, :3].ravel().tolist()])
    image.info["transparency"] = 0
    return image


def _lon_to_x(lon: float, zoom: int) -> float:
    return (lon + 180) / 360 * 2**zoom


def _lat_to_y(lat: float, zoom: int) -> float:
    rad = math.radians(lat)
    return (1 - math.asinh(math.tan(rad)) / math.pi) / 2 * 2**zoom


def tiles_covering(grid: Grid, zoom: int) -> list[tuple[int, int, int]]:
    xmin, ymin, xmax, ymax = grid.bounds
    last = 2**zoom - 1
    x0, x1 = int(_lon_to_x(xmin, zoom)), min(int(_lon_to_x(xmax, zoom)), last)
    y0, y1 = int(_lat_to_y(ymax, zoom)), min(int(_lat_to_y(ymin, zoom)), last)
    return [(zoom, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def render_tile(
    values: np.ndarray, grid: Grid, layer: LayerDefinition, z: int, x: int, y: int
) -> bytes | None:
    """Palette PNG of one web-mercator tile, sampled nearest-cell; None if it holds no values."""
    n = 2**z
    px = (x + (np.arange(TILE_SIZE) + 0.5) / TILE_SIZE) / n
    py = (y + (np.arange(TILE_SIZE) + 0.5) / TILE_SIZE) / n
    lon = px * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * py))))
    col = np.floor((lon - grid.x0) / CELL).astype(int)
    row = np.floor((grid.y0 - lat) / CELL).astype(int)
    col_ok = (col >= 0) & (col < grid.width)
    row_ok = (row >= 0) & (row < grid.height)
    if not col_ok.any() or not row_ok.any():
        return None
    sampled = np.full((TILE_SIZE, TILE_SIZE), np.nan)
    inside = row_ok[:, None] & col_ok[None, :]
    rows, cols = np.broadcast_arrays(row[:, None], col[None, :])
    sampled[inside] = values[rows[inside], cols[inside]]
    if np.isnan(sampled).all():
        return None
    buffer = io.BytesIO()
    _palette_image(sampled, layer).save(buffer, "PNG", optimize=True, transparency=0)
    return buffer.getvalue()


def write_pmtiles(
    path: Path,
    values: np.ndarray,
    grid: Grid,
    layer: LayerDefinition,
    min_zoom: int = MIN_ZOOM,
    max_zoom: int = MAX_ZOOM,
    metadata: dict | None = None,
) -> None:
    """Write one (height, width) array as a raster PMTiles archive."""
    tiles = {}
    for zoom in range(min_zoom, max_zoom + 1):
        for z, x, y in tiles_covering(grid, zoom):
            png = render_tile(values, grid, layer, z, x, y)
            if png is not None:
                tiles[zxy_to_tileid(z, x, y)] = png

    xmin, ymin, xmax, ymax = grid.bounds
    path.parent.mkdir(parents=True, exist_ok=True)
    with write(str(path)) as writer:
        for tile_id in sorted(tiles):
            writer.write_tile(tile_id, tiles[tile_id])
        writer.finalize(
            {
                "tile_type": TileType.PNG,
                "tile_compression": Compression.NONE,
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "min_lon_e7": int(xmin * 1e7),
                "min_lat_e7": int(ymin * 1e7),
                "max_lon_e7": int(xmax * 1e7),
                "max_lat_e7": int(ymax * 1e7),
                "center_zoom": min_zoom,
                "center_lon_e7": int((xmin + xmax) / 2 * 1e7),
                "center_lat_e7": int((ymin + ymax) / 2 * 1e7),
            },
            {"layer": layer.id, "name": layer.name, "units": layer.units, **(metadata or {})},
        )
