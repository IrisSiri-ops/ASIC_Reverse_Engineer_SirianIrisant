import gdspy
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

GDS_FILE = os.path.join(PUZZLE_DIR, "puzzle.gds")
TOP_CELL = "puzzle"
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1b_clkbuf_instances.json")

# Mirror of Stage 1's FILLER_KEYWORDS filter, but inverted: Stage 1 excludes
# anything matching "clkbuf"; this script keeps ONLY cells matching "clkbuf".
# Same is_sky130_stdcell gate as Stage 1, so non-stdcell references
# (VIA_*, INTERNAL_* easter eggs) are excluded here too, consistent with Stage 1.


def is_clkbuf(cell_name):
    return "clkbuf" in cell_name.lower()


def is_sky130_stdcell(cell_name):
    return cell_name.startswith("sky130_fd_sc_hd__")


def main():
    print("=== PUZZLE STAGE 1b: Clock Buffer Instance Extraction ===")
    print(f"Loading {GDS_FILE}...")

    gds = gdspy.GdsLibrary(infile=GDS_FILE)
    top_cell = gds.cells[TOP_CELL]

    print(f"Top cell '{TOP_CELL}' has {len(top_cell.references)} total references")

    instances = []
    skipped_non_stdcell = 0
    skipped_non_clkbuf = 0

    for ref in top_cell.references:
        cell_name = ref.ref_cell.name

        if not is_sky130_stdcell(cell_name):
            skipped_non_stdcell += 1
            continue

        if not is_clkbuf(cell_name):
            skipped_non_clkbuf += 1
            continue

        instances.append({
            "instance_id": len(instances),
            "cell_type": cell_name,
            "position": [float(ref.origin[0]), float(ref.origin[1])],
            "rotation": float(ref.rotation) if ref.rotation else 0.0,
            "x_reflection": bool(ref.x_reflection) if hasattr(ref, 'x_reflection') else False,
        })

    print(f"\nExcluded (non-stdcell: VIA_*, INTERNAL_*, etc.): {skipped_non_stdcell}")
    print(f"Excluded (stdcell but not clkbuf): {skipped_non_clkbuf}")
    print(f"Kept {len(instances)} clkbuf instances")

    counts = {}
    for inst in instances:
        ct = inst["cell_type"]
        counts[ct] = counts.get(ct, 0) + 1

    print(f"\nBreakdown by clkbuf type ({len(counts)} unique types):")
    for ct in sorted(counts.keys()):
        print(f"  {ct}: {counts[ct]}")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(instances, f, indent=2)
    print(f"\n✓ Saved to {OUTPUT_FILE}")

    # Cross-check against Stage 1's own instance count: instance_id numbering
    # in this file is independent of Stage 1's (both start at 0), which is
    # fine since Stage 1c/6a key gate vs. clkbuf lookups by cell_type +
    # instance_id together, not a globally unique id across both files.
    # Just flagging this explicitly since it's an easy place for a future
    # bug to hide if that assumption ever changes.


if __name__ == "__main__":
    main()