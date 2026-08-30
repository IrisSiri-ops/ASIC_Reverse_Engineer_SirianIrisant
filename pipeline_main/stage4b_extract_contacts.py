import gdspy
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

GDS_FILE = os.path.join(PUZZLE_DIR, "puzzle.gds")
TOP_CELL = "puzzle"
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage4b_contacts.json")

CONTACT_LAYERS = {
    (66, 44): ("licon1", "poly_diff", "li1"),
    (67, 44): ("mcon",   "li1",       "met1"),
    (68, 44): ("via",    "met1",      "met2"),
    (69, 44): ("via2",   "met2",      "met3"),
    (70, 44): ("via3",   "met3",      "met4"),
    (71, 44): ("via4",   "met4",      "met5"),
}


def centroid(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0]


def main():
    print("=== PUZZLE STAGE 4b: Contact Cut Geometry ===\n")

    gds = gdspy.GdsLibrary(infile=GDS_FILE)
    top_cell = gds.cells[TOP_CELL]
    by_spec = top_cell.get_polygons(by_spec=True)

    contacts = {}
    total = 0

    for (layer, datatype), (name, below, above) in CONTACT_LAYERS.items():
        key = (layer, datatype)
        shapes = by_spec.get(key, [])
        entries = [{"position": centroid(poly.tolist()), "connects": [below, above]} for poly in shapes]
        contacts[name] = entries
        total += len(entries)
        print(f"  {name} ({layer}/{datatype}): {len(entries)} contacts  [{below} <-> {above}]")

    print(f"\nTotal contacts extracted: {total}")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(contacts, f, indent=2)

    print(f"\n✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
