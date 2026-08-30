import json
import math
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

INSTANCES_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1_instances.json")
CELL_PINS_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage2_cell_pins.json")
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage3_absolute_pins.json")

# Metadata/annotation labels that aren't real pins -- found on conb_1 so far,
# may exist on other cell types too. Extend this set if new leaks show up.
NON_PIN_LABELS = {"resistive_li1_ok", "no_jumper_check"}


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


def is_real_pin(pin_name, base_name):
    if pin_name == base_name:
        return False
    if pin_name in NON_PIN_LABELS:
        return False
    return True


def main():
    print("=== PUZZLE STAGE 3 (CORRECTED): Absolute Pin Positions ===")

    with open(INSTANCES_FILE) as f:
        instances = json.load(f)
    with open(CELL_PINS_FILE) as f:
        cell_pins = json.load(f)

    results = []
    skipped_non_pin = 0

    for inst in instances:
        cell_type = inst["cell_type"]
        inst_x, inst_y = inst["position"]
        rotation = inst["rotation"]
        x_reflection = inst["x_reflection"]

        if cell_type not in cell_pins:
            continue

        base_name = get_base_name(cell_type)
        pins_absolute = {}

        for pin_name, pin_info in cell_pins[cell_type].items():
            if not is_real_pin(pin_name, base_name):
                skipped_non_pin += 1
                continue

            px, py = pin_info["position"]
            abs_x, abs_y = transform_point(px, py, rotation, x_reflection, inst_x, inst_y)
            pins_absolute[pin_name] = {
                "position": [round(abs_x, 4), round(abs_y, 4)],
                "layer_name": pin_info["layer_name"],
                "layer_num": pin_info["layer_num"],
            }

        results.append({
            "instance_id": inst["instance_id"],
            "cell_type": cell_type,
            "pins": pins_absolute,
        })

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Processed {len(results)} instances")
    print(f"Skipped non-pin labels (self-name + metadata annotations): {skipped_non_pin}")

    layer_counts = {}
    for r in results:
        for pin_name, info in r["pins"].items():
            layer_counts[info["layer_name"]] = layer_counts.get(info["layer_name"], 0) + 1
    print("\nPin count by layer:")
    for layer, count in sorted(layer_counts.items()):
        print(f"  {layer}: {count}")

    # Explicit check: any layer other than li1/met1/nwell present? Should be none.
    unexpected_layers = set(layer_counts.keys()) - {"li1", "met1", "nwell"}
    if unexpected_layers:
        print(f"\n⚠️ Unexpected layers still present: {unexpected_layers}")
    else:
        print(f"\n✓ Only li1/met1/nwell present -- clean")

    print(f"\n✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
