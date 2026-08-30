import gdspy
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

GDS_FILE = os.path.join(PUZZLE_DIR, "puzzle.gds")
TOP_CELL = "puzzle"
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1_instances.json")

# Same filter categories as warmup, proven correct there.
# clkbuf (all sizes) excluded here too -- handled separately in Stage 1b, same pattern as warmup.
FILLER_KEYWORDS = {"decap", "tap", "via", "clkbuf"}


def is_filler(cell_name):
    return any(keyword in cell_name.lower() for keyword in FILLER_KEYWORDS)


def is_sky130_stdcell(cell_name):
    return cell_name.startswith("sky130_fd_sc_hd__")


def main():
    print("=== PUZZLE STAGE 1: Instance Extraction ===")
    print(f"Loading {GDS_FILE}...")

    gds = gdspy.GdsLibrary(infile=GDS_FILE)
    top_cell = gds.cells[TOP_CELL]

    print(f"Top cell '{TOP_CELL}' has {len(top_cell.references)} total references")

    instances = []
    filler_count = 0
    non_stdcell_count = 0  # INTERNAL_3/7 easter egg, etc.

    for ref in top_cell.references:
        cell_name = ref.ref_cell.name

        if not is_sky130_stdcell(cell_name):
            # not a standard cell at all -- includes VIA_*, INTERNAL_* easter eggs
            non_stdcell_count += 1
            continue

        if is_filler(cell_name):
            filler_count += 1
            continue

        instances.append({
            "instance_id": len(instances),
            "cell_type": cell_name,
            "position": [float(ref.origin[0]), float(ref.origin[1])],
            "rotation": float(ref.rotation) if ref.rotation else 0.0,
            "x_reflection": bool(ref.x_reflection) if hasattr(ref, 'x_reflection') else False,
        })

    print(f"\nExcluded (non-stdcell: VIA_*, INTERNAL_*, etc.): {non_stdcell_count}")
    print(f"Excluded (filler: decap/tap/via/clkbuf): {filler_count}")
    print(f"Kept {len(instances)} real logic gate instances")

    counts = {}
    for inst in instances:
        ct = inst["cell_type"]
        counts[ct] = counts.get(ct, 0) + 1

    print(f"\nBreakdown by cell type ({len(counts)} unique types):")
    for ct in sorted(counts.keys()):
        print(f"  {ct}: {counts[ct]}")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(instances, f, indent=2)
    print(f"\n✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
