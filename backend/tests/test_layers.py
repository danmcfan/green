import json

import pytest

from green.layers import LayerDefinition, load_layers


def write(tmp_path, layers):
    path = tmp_path / "layers.json"
    path.write_text(json.dumps({"layers": layers}))
    return path


NDVI = {
    "id": "observed_ndvi",
    "name": "Observed NDVI",
    "kind": "observed",
    "units": "NDVI",
    "range": [0, 1],
    "colors": ["#a0522d", "#228b22"],
}


def test_loads_repo_layer_file():
    layers = load_layers()
    assert "observed_ndvi" in layers
    assert "predicted_ndvi" in layers


def test_parses_layer_fields(tmp_path):
    layers = load_layers(write(tmp_path, [NDVI]))
    assert layers["observed_ndvi"] == LayerDefinition(
        id="observed_ndvi",
        name="Observed NDVI",
        kind="observed",
        units="NDVI",
        range=(0.0, 1.0),
        colors=("#a0522d", "#228b22"),
    )


def test_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_layers(write(tmp_path, [NDVI, NDVI]))


def test_rejects_inverted_range(tmp_path):
    with pytest.raises(ValueError, match="range"):
        load_layers(write(tmp_path, [{**NDVI, "range": [1, 0]}]))


def test_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError, match="kind"):
        load_layers(write(tmp_path, [{**NDVI, "kind": "feature"}]))


def test_rejects_too_few_colors(tmp_path):
    with pytest.raises(ValueError, match="colors"):
        load_layers(write(tmp_path, [{**NDVI, "colors": ["#000000"]}]))
