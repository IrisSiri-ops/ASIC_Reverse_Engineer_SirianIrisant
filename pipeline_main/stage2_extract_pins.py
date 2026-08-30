import gdspy
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

GDS_FILE = os.path.join(PUZZLE_DIR, "puzzle.gds")
INSTANCES_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1_instances.json")
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage2_cell_pins.json")

LAYER_NAMES = {
    64: "nwell", 66: "poly", 67: "li1", 68: "met1",
    69: "met2", 70: "met3", 71: "met4", 72: "met5", 83: "text",
}


def main():
    print("=== PUZZLE STAGE 2: Cell Pin Definitions ===\n")

    with open(INSTANCES_FILE) as f:
        instances = json.load(f)
    needed_cell_types = sorted(set(inst["cell_type"] for inst in instances))
    print(f"Need pin definitions for {len(needed_cell_types)} cell types")

    gds = gdspy.GdsLibrary(infile=GDS_FILE)
    cell_pins = {}
    missing = []

    for cell_type in needed_cell_types:
        if cell_type not in gds.cells:
            missing.append(cell_type)
            continue
        cell = gds.cells[cell_type]
        if not hasattr(cell, 'labels') or not cell.labels:
            missing.append(cell_type)
            continue

        pins = {}
        for label in cell.labels:
            text = getattr(label, 'text', None)
            pos = getattr(label, 'position', None)
            layer = getattr(label, 'layer', None)
            if text is None or pos is None:
                continue
            if text not in pins:
                pins[text] = {
                    "position": [float(pos[0]), float(pos[1])],
                    "layer_num": int(layer) if layer is not None else None,
                    "layer_name": LAYER_NAMES.get(int(layer), f"unknown_{layer}") if layer is not None else "unknown",
                }
        cell_pins[cell_type] = pins

    if missing:
        print(f"⚠️ {len(missing)} cell types missing pin data: {missing}")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(cell_pins, f, indent=2)

    # Layer summary, same sanity check as warmup
    layer_usage = {}
    for cell_type, pins in cell_pins.items():
        for pin_name, info in pins.items():
            key = f"{info['layer_name']} ({info['layer_num']})"
            layer_usage.setdefault(key, set()).add(pin_name)

    print("\n=== Pin layer summary ===")
    for layer_key in sorted(layer_usage.keys()):
        pin_names = sorted(layer_usage[layer_key])
        print(f"{layer_key}: {len(pin_names)} distinct pin names")
        print(f"  {', '.join(pin_names[:20])}{'...' if len(pin_names) > 20 else ''}")

    print(f"\n✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
