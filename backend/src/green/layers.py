"""Read the shared Layer definition file (ADR 0004)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

Kind = Literal["input", "observed", "predicted", "derived"]

LAYERS_FILE = Path(__file__).resolve().parents[3] / "layers.json"


@dataclass(frozen=True)
class LayerDefinition:
    id: str
    name: str
    kind: Kind
    units: str
    range: tuple[float, float]
    colors: tuple[str, ...]


def _parse(raw: dict) -> LayerDefinition:
    layer_id = raw["id"]
    if raw["kind"] not in get_args(Kind):
        raise ValueError(f"{layer_id}: unknown kind {raw['kind']!r}")
    low, high = (float(v) for v in raw["range"])
    if low >= high:
        raise ValueError(f"{layer_id}: range minimum must be below maximum")
    if len(raw["colors"]) < 2:
        raise ValueError(f"{layer_id}: colors needs at least two stops")
    return LayerDefinition(
        id=layer_id,
        name=raw["name"],
        kind=raw["kind"],
        units=raw["units"],
        range=(low, high),
        colors=tuple(raw["colors"]),
    )


def load_layers(path: Path = LAYERS_FILE) -> dict[str, LayerDefinition]:
    """Return every Layer definition in the file, keyed by id."""
    layers: dict[str, LayerDefinition] = {}
    for raw in json.loads(path.read_text())["layers"]:
        layer = _parse(raw)
        if layer.id in layers:
            raise ValueError(f"duplicate layer id {layer.id!r}")
        layers[layer.id] = layer
    return layers
