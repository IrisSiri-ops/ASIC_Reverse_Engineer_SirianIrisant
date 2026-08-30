"""
Stage 7b: Unmatched Pin Diagnostic
====================================

Purpose
-------
stage6a_pin_net_map.json reports 1,476 pins with net_id=None out of ~738
instances. Stage 6b/6c silently DROPS any pin with net_id=None from the
emitted Verilog instantiation -- meaning a meaningful fraction of gate
ports may simply be missing from puzzle_recovered_final.v, which is
sufficient on its own to explain all-X simulation output via X-propagation,
independent of the clkbuf/clock-tree question (already ruled out separately).

This script does not fix anything. It breaks down WHERE the 1,476 misses
are concentrated, so the next fix is targeted rather than guessed at:

  1. Power/well pins (VPWR/VGND/VPB/VNB) vs. real logic pins
     -- power pins are often handled via a separate mechanism (e.g. a single
        global VPWR/VGND tie) elsewhere in your flow, so misses here may be
        expected and harmless. Misses on A/B/X/Y/CLK/etc. are NOT harmless.
  2. Breakdown by pin name (which specific pins are failing to match)
  3. Breakdown by cell type (does this concentrate on a few cell types,
     suggesting a per-cell-type geometry issue, e.g. an unusual pin layer
     Stage 6a isn't checking, or a label position convention that differs
     for that cell)
  4. Breakdown by layer (recall: Stage 6a only checks `layer in metal`,
     i.e. only layers present in stage4_routing_geometry.json's keys --
     if any pin layer isn't one of those keys, EVERY pin on that layer
     silently fails to match, regardless of geometry)
  5. A handful of concrete example misses (instance_id, cell_type, pin_name,
     position) so you can spot-check a couple by hand in KLayout or via
     inspect_net.py-style coordinate lookup.
"""

import json
import os
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "pipeline_main" else SCRIPT_DIR
OUTPUT_DIR = os.path.join(PUZZLE_DIR, "output_main")

PIN_NET_FILE = os.path.join(OUTPUT_DIR, "stage6a_pin_net_map.json")
PINS_FILE = os.path.join(OUTPUT_DIR, "stage3_absolute_pins.json")
CLKBUF_PINS_FILE = os.path.join(OUTPUT_DIR, "stage1b_clkbuf_pins.json")
METAL_FILE = os.path.join(OUTPUT_DIR, "stage4_routing_geometry.json")

POWER_PINS = {"VPWR", "VGND", "VPB", "VNB"}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def build_position_lookup():
    """instance_id -> {pin_name: {position, layer_name}}, from stage3 + clkbuf pins."""
    lookup = {}
    for src in (PINS_FILE, CLKBUF_PINS_FILE):
        if not os.path.exists(src):
            continue
        for inst in load_json(src):
            lookup.setdefault(inst["instance_id"], {}).update(inst["pins"])
    return lookup


def main():
    print("=== Stage 7b: Unmatched Pin Diagnostic ===\n")

    data = load_json(PIN_NET_FILE)
    pin_net_map = data["pin_net_map"]

    metal = load_json(METAL_FILE) if os.path.exists(METAL_FILE) else {}
    metal_layers_present = set(metal.keys())
    print(f"Layers present in stage4 metal geometry: {sorted(metal_layers_present)}\n")

    total = len(pin_net_map)
    unmatched = [p for p in pin_net_map if p["net_id"] is None]
    matched = total - len(unmatched)

    print(f"Total pins: {total}")
    print(f"Matched: {matched} ({100*matched/total:.1f}%)")
    print(f"Unmatched: {len(unmatched)} ({100*len(unmatched)/total:.1f}%)\n")

    # --- 1. Power vs non-power split ---
    unmatched_power = [p for p in unmatched if p["pin_name"] in POWER_PINS]
    unmatched_logic = [p for p in unmatched if p["pin_name"] not in POWER_PINS]

    print("=== 1. Power vs. Logic Pin Split (unmatched only) ===")
    print(f"Unmatched power pins (VPWR/VGND/VPB/VNB): {len(unmatched_power)}")
    print(f"Unmatched LOGIC pins (everything else):    {len(unmatched_logic)}")
    if unmatched_logic:
        print(f"⚠️  {len(unmatched_logic)} real logic pins are missing from the netlist entirely.")
        print(f"    These are silently dropped by stage6bc_emit_netlist.py.")
    print()

    # --- 2. Breakdown by pin name ---
    print("=== 2. Unmatched Count by Pin Name ===")
    pin_name_counts = Counter(p["pin_name"] for p in unmatched)
    for pin_name, count in pin_name_counts.most_common(20):
        tag = "(power)" if pin_name in POWER_PINS else ""
        print(f"  {pin_name:12s} {count:5d}  {tag}")
    print()

    # --- 3. Breakdown by cell type (logic pins only, power noise removed) ---
    print("=== 3. Unmatched LOGIC Pins by Cell Type (top 20) ===")
    cell_type_counts = Counter(p["cell_type"] for p in unmatched_logic)
    for cell_type, count in cell_type_counts.most_common(20):
        print(f"  {cell_type:40s} {count:5d}")
    if not cell_type_counts:
        print("  (none -- all unmatched pins are power pins)")
    print()

    # --- 4. Breakdown by layer ---
    print("=== 4. Unmatched Pins by Layer ===")
    # Need pin layer info -- pull from stage3/stage1b pin position data
    pos_lookup = build_position_lookup()
    layer_counts = Counter()
    layer_missing_from_metal = Counter()
    for p in unmatched:
        inst_pins = pos_lookup.get(p["instance_id"], {})
        info = inst_pins.get(p["pin_name"])
        layer = info["layer_name"] if info else "UNKNOWN (position lookup failed)"
        layer_counts[layer] += 1
        if layer not in metal_layers_present and layer != "UNKNOWN (position lookup failed)":
            layer_missing_from_metal[layer] += 1

    for layer, count in layer_counts.most_common():
        flag = ""
        if layer in layer_missing_from_metal:
            flag = f"  ⚠️ layer '{layer}' has NO geometry in stage4_routing_geometry.json -- EVERY pin on this layer will always fail to match, regardless of actual connectivity"
        print(f"  {layer:15s} {count:5d}{flag}")
    print()

    # --- 5. Concrete examples for manual spot-check ---
    print("=== 5. Sample Unmatched LOGIC Pins (for manual spot-check) ===")
    for p in unmatched_logic[:15]:
        inst_pins = pos_lookup.get(p["instance_id"], {})
        info = inst_pins.get(p["pin_name"], {})
        pos = info.get("position", "?")
        layer = info.get("layer_name", "?")
        print(f"  instance_id={p['instance_id']:4d}  cell_type={p['cell_type']:35s} "
              f"pin={p['pin_name']:6s} layer={layer:6s} pos={pos}")

    print("\n=== Summary ===")
    if unmatched_logic:
        top_layer = layer_counts.most_common(1)[0][0] if layer_counts else None
        if top_layer in layer_missing_from_metal:
            print(f"Most unmatched logic pins are on layer '{top_layer}', which has NO")
            print(f"geometry extracted in Stage 4a at all. This is a Stage 4a/Stage 6a")
            print(f"layer-coverage gap, not a Stage 5 connectivity bug -- Stage 6a's")
            print(f"`if layer in metal` check silently skips ANY pin on a layer that")
            print(f"was never extracted, regardless of whether real copper exists there.")
        else:
            print(f"Unmatched logic pins are NOT concentrated on a missing layer -- the")
            print(f"cause is more likely genuine point-in-polygon misses (pin sits exactly")
            print(f"on a polygon boundary/vertex, or geometry is fragmented at that pin's")
            print(f"exact coordinate). Cross-check a few of the sample coordinates above")
            print(f"directly in KLayout.")
    else:
        print("All unmatched pins are power pins -- if VPWR/VGND are tied globally")
        print("elsewhere in your flow, this is likely expected and not the cause of")
        print("the all-X simulation result.")


if __name__ == "__main__":
    main()
