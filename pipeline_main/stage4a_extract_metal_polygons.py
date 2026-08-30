import gdspy
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

GDS_FILE = os.path.join(PUZZLE_DIR, "puzzle.gds")
TOP_CELL = "puzzle"
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage4_routing_geometry.json")

METAL_LAYERS = {
    (64, 20): "nwell",
    (67, 20): "li1",
    (68, 20): "met1",
    (69, 20): "met2",
    (70, 20): "met3",
    (71, 20): "met4",
    (72, 20): "met5",
}


def main():
    print("=== PUZZLE STAGE 4a: Extract Metal Polygons ===\n")

    gds = gdspy.GdsLibrary(infile=GDS_FILE)
    top_cell = gds.cells[TOP_CELL]

    by_spec = top_cell.get_polygons(by_spec=True)

    shapes = {}
    for (layer, datatype), name in METAL_LAYERS.items():
        key = (layer, datatype)
        shapes[name] = [p.tolist() for p in by_spec.get(key, [])]

    print("=== Extracted shapes by layer ===")
    for name, polys in shapes.items():
        print(f"  {name}: {len(polys)} polygons")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(shapes, f, indent=2)

    print(f"\n✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
