from green.layers import load_layers


def main() -> None:
    for layer in load_layers().values():
        print(f"{layer.id}: {layer.name} ({layer.units})")
