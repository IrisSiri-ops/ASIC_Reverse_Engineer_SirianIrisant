"""
====================================================================
PHASE 1: PORT RE-DERIVATION
====================================================================
Everything from here forward re-derives what the original (lost) session
had already established, before moving past it into new work (Stage 6d
netlist emission, then the Phase 2+ custom simulator).

Stage 8: Top-Level Port Lookup
--------------------------------

Purpose
-------
Locates the 6 known top-level ports (clk, rst_n, enable, I, success, O[0:7])
by finding their literal text labels at the top level of puzzle.gds, then
resolves each label's position to a net_id using the same point-in-polygon +
rect_to_net approach Stage 6a already uses for gate pins.

This replaces the never-recovered lookup_all_ports.py from scratch, using
ONLY information present in the GDS itself (label text + position) --
consistent with the "GDS in, answer out" framing: no hardcoded coordinates
or net_ids are assumed here, they are re-derived from the file directly.

Expects Stages 4a (stage4_routing_geometry.json) and 5 (stage5_nets.json)
to have already been run.
"""

import gdspy
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

GDS_FILE = os.path.join(PUZZLE_DIR, "puzzle.gds")
TOP_CELL = "puzzle"
METAL_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage4_routing_geometry.json")
NETS_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage5_nets.json")
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage8_port_map.json")

# Layer numbers, same convention as Stage 4a
LAYER_NAMES = {
    64: "nwell", 67: "li1", 68: "met1",
    69: "met2", 70: "met3", 71: "met4", 72: "met5",
}

EXPECTED_PORTS = {"clk", "rst_n", "enable", "I", "success",
                  "O[0]", "O[1]", "O[2]", "O[3]", "O[4]", "O[5]", "O[6]", "O[7]"}


def point_in_polygon(px, py, poly, tol=0.005):
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py):
            if px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi:
                inside = not inside
        j = i
    return inside


def main():
    print("=== PUZZLE STAGE 8 (Phase 1: Port Re-Derivation) — Top-Level Port Lookup ===\n")

    gds = gdspy.GdsLibrary(infile=GDS_FILE)
    top_cell = gds.cells[TOP_CELL]

    print(f"Top-level labels found: {len(top_cell.labels)}")
    for l in top_cell.labels:
        layer_name = LAYER_NAMES.get(l.layer, f"unknown_{l.layer}")
        tag = "  <-- expected port" if l.text in EXPECTED_PORTS else ""
        print(f"  '{l.text}'  pos={tuple(l.position)}  layer={layer_name}{tag}")

    with open(METAL_FILE) as f:
        metal = json.load(f)
    with open(NETS_FILE) as f:
        nets = json.load(f)

    rect_to_net = {}
    for net_id, net in enumerate(nets):
        for m in net["members"]:
            rect_to_net[(m["layer"], m["index"])] = net_id

    port_map = {}
    unresolved = []

    for label in top_cell.labels:
        text = label.text
        if text not in EXPECTED_PORTS:
            continue  # skip VGND/VPWR power strap labels etc.

        px, py = float(label.position[0]), float(label.position[1])
        layer_name = LAYER_NAMES.get(label.layer)

        found_net = None
        if layer_name in metal:
            for idx, poly in enumerate(metal[layer_name]):
                if point_in_polygon(px, py, poly):
                    found_net = rect_to_net.get((layer_name, idx))
                    break

        if found_net is None:
            unresolved.append(text)
            print(f"⚠️  '{text}' at ({px}, {py}) on {layer_name} did not resolve to a net")
        else:
            port_map[text] = {
                "net_id": found_net,
                "position": [px, py],
                "layer": layer_name,
            }

    missing = EXPECTED_PORTS - set(port_map.keys()) - set(unresolved)
    if missing:
        print(f"\n⚠️  Expected ports with NO label found at all in GDS: {sorted(missing)}")

    print(f"\n=== Resolved Port Map ===")
    for name in sorted(port_map.keys()):
        info = port_map[name]
        print(f"  {name:10s} -> net_id={info['net_id']:5d}  ({info['layer']}, pos={info['position']})")

    if unresolved:
        print(f"\n⚠️  {len(unresolved)} labels found but did not resolve to any net: {unresolved}")
        print("   (worth checking these against stage6b_net_names.json's port_candidate_* entries")
        print("    by coordinate, in case point-in-polygon just missed due to a boundary case)")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(port_map, f, indent=2)
    print(f"\n✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()