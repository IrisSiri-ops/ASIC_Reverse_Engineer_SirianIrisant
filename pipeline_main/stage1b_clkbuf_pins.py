import gdspy
import json
import os
import math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

GDS_FILE = os.path.join(PUZZLE_DIR, "puzzle.gds")
CLKBUF_INSTANCES_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1b_clkbuf_instances.json")
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1b_clkbuf_pins.json")

LAYER_NAMES = {64: "nwell", 66: "poly", 67: "li1", 68: "met1", 69: "met2", 83: "text"}


def transform_point(px, py, rotation_deg, x_reflection, inst_x, inst_y):
    x, y = px, py
    if x_reflection:
        y = -y
    rad = math.radians(rotation_deg)
    cos_r, sin_r = round(math.cos(rad), 10), round(math.sin(rad), 10)
    new_x = x * cos_r - y * sin_r
    new_y = x * sin_r + y * cos_r
    return new_x + inst_x, new_y + inst_y


def get_base_name(cell_type):
    prefix = "sky130_fd_sc_hd__"
    return cell_type[len(prefix):] if cell_type.startswith(prefix) else cell_type


def main():
    print("=== PUZZLE STAGE 1b: Clock Buffer Pin Positions ===\n")

    gds = gdspy.GdsLibrary(infile=GDS_FILE)
    with open(CLKBUF_INSTANCES_FILE) as f:
        clkbuf_instances = json.load(f)

    cell_types_needed = sorted(set(i["cell_type"] for i in clkbuf_instances))
    cell_pins = {}
    for cell_type in cell_types_needed:
        cell = gds.cells[cell_type]
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
        print(f"{cell_type}: pins = {sorted(pins.keys())}")

    results = []
    for inst in clkbuf_instances:
        cell_type = inst["cell_type"]
        base_name = get_base_name(cell_type)
        pins_absolute = {}
        for pin_name, pin_info in cell_pins[cell_type].items():
            if pin_name == base_name:
                continue
            px, py = pin_info["position"]
            abs_x, abs_y = transform_point(
                px, py, inst["rotation"], inst["x_reflection"],
                inst["position"][0], inst["position"][1]
            )
            pins_absolute[pin_name] = {
                "position": [round(abs_x, 4), round(abs_y, 4)],
                "layer_name": pin_info["layer_name"],
                "layer_num": pin_info["layer_num"],
            }
        results.append({"instance_id": inst["instance_id"], "cell_type": cell_type, "pins": pins_absolute})

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nProcessed {len(results)} clkbuf instances")
    print(f"✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
