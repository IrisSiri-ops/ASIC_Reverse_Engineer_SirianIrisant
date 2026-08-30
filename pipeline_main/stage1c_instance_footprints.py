import gdspy
import json
import os
import math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

GDS_FILE = os.path.join(PUZZLE_DIR, "puzzle.gds")
INSTANCES_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1_instances.json")
CLKBUF_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1b_clkbuf_instances.json")
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1c_instance_footprints.json")


def transform_point(px, py, rotation_deg, x_reflection, inst_x, inst_y):
    x, y = px, py
    if x_reflection:
        y = -y
    rad = math.radians(rotation_deg)
    cos_r, sin_r = round(math.cos(rad), 10), round(math.sin(rad), 10)
    new_x = x * cos_r - y * sin_r
    new_y = x * sin_r + y * cos_r
    return new_x + inst_x, new_y + inst_y


def compute_footprints(gds, instances):
    footprints = []
    missing = []
    for inst in instances:
        cell_type = inst["cell_type"]
        if cell_type not in gds.cells:
            missing.append(cell_type)
            continue
        cell = gds.cells[cell_type]
        bbox = cell.get_bounding_box()
        if bbox is None:
            missing.append(cell_type)
            continue
        (lx, ly), (hx, hy) = bbox
        corners = [(lx, ly), (lx, hy), (hx, ly), (hx, hy)]
        transformed = [
            transform_point(cx, cy, inst["rotation"], inst["x_reflection"], inst["position"][0], inst["position"][1])
            for cx, cy in corners
        ]
        xs = [p[0] for p in transformed]
        ys = [p[1] for p in transformed]
        footprints.append({
            "instance_id": inst["instance_id"],
            "cell_type": cell_type,
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
        })
    return footprints, missing


def main():
    print("=== PUZZLE STAGE 1c: Instance Footprints (gates + clkbuf) ===\n")

    gds = gdspy.GdsLibrary(infile=GDS_FILE)

    with open(INSTANCES_FILE) as f:
        gate_instances = json.load(f)
    with open(CLKBUF_FILE) as f:
        clkbuf_instances = json.load(f)

    gate_footprints, missing1 = compute_footprints(gds, gate_instances)
    clkbuf_footprints, missing2 = compute_footprints(gds, clkbuf_instances)

    all_footprints = gate_footprints + clkbuf_footprints

    if missing1 or missing2:
        print(f"⚠️ Missing footprints for: {set(missing1 + missing2)}")

    print(f"Gate footprints: {len(gate_footprints)}")
    print(f"Clkbuf footprints: {len(clkbuf_footprints)}")
    print(f"Total: {len(all_footprints)}")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_footprints, f, indent=2)

    print(f"\n✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
