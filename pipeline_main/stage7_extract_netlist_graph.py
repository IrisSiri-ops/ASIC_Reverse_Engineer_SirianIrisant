"""
Stage 7: Netlist Graph Extraction + Clock-Tree Reachability BFS
=================================================================

Purpose
-------
Builds a clean, queryable netlist graph from the existing pipeline outputs
(stage1_instances.json, stage1b_clkbuf_instances.json, stage6a_pin_net_map.json,
stage6b_net_names.json), rather than working directly against the flat
pin_net_map list. This graph form is reusable for:
  - the clock-tree reachability BFS below (immediate use)
  - a future custom Python gate-level simulator (build the dependency graph
    directly from this structure instead of re-parsing JSON each time)
  - any other net-level query (fan-in/fan-out, net size histograms, etc.)

This script does NOT touch or re-run Stage 5. It only consumes what Stage 6a
already decided about pin-to-net assignment, and asks a structural question
of it: starting from the `clk` net, how much of the clock tree is actually
reachable, and which flip-flops are NOT reached?

Assumptions (flag if these don't match your repo)
---------------------------------------------------
- Cell types containing "dfrtp" or "dfstp" are flip-flops (standard Sky130
  sequential cell naming: D Flip-flop Reset/Set, Positive-edge triggered).
  Their clock pin is named "CLK".
- Cell types containing "clkbuf" are clock buffers, with input pin "A" and
  output pin "X".
- The top-level `clk` port net is identified via stage6b_net_names.json by
  matching net_id == 623 (per your earlier port lookup), OR by name
  "port_candidate_08" if the numeric id shifted between runs. Both are
  checked; mismatch is reported loudly rather than silently guessed.
"""

import json
import os
import sys
from collections import defaultdict, deque

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "pipeline_main" else SCRIPT_DIR
OUTPUT_DIR = os.path.join(PUZZLE_DIR, "output_main")

INSTANCES_FILE      = os.path.join(OUTPUT_DIR, "stage1_instances.json")
CLKBUF_FILE         = os.path.join(OUTPUT_DIR, "stage1b_clkbuf_instances.json")
PIN_NET_FILE         = os.path.join(OUTPUT_DIR, "stage6a_pin_net_map.json")
NET_NAMES_FILE       = os.path.join(OUTPUT_DIR, "stage6b_net_names.json")
FOOTPRINT_FILE       = os.path.join(OUTPUT_DIR, "stage1c_instance_footprints.json")

OUTPUT_GRAPH_FILE    = os.path.join(OUTPUT_DIR, "stage7_netlist_graph.json")

# Known clk port net_id from your physical pad-label lookup (lookup_all_ports.py).
# If this doesn't match what's actually in the data, the script will tell you.
KNOWN_CLK_NET_ID = 623
KNOWN_CLK_NET_NAME = "port_candidate_08"

# --- Optional: output generator bounding box, in absolute chip coordinates.
# Fill this in from the layout image / your own coordinate lookups if you have it,
# to enable the "does the unreached set cluster here" cross-check.
# Leave as None to skip that check.
OUTPUT_GENERATOR_BBOX = None  # e.g. (110.0, 150.0, 145.0, 290.0)  # (x0, y0, x1, y1)


def load_json(path):
    if not os.path.exists(path):
        print(f"ERROR: expected file not found: {path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def is_flipflop(cell_type):
    ct = cell_type.lower()
    return "dfrtp" in ct or "dfstp" in ct or "dfxtp" in ct


def is_clkbuf(cell_type):
    return "clkbuf" in cell_type.lower()


def build_graph():
    print("=== Stage 7: Netlist Graph Extraction ===\n")

    gate_instances = load_json(INSTANCES_FILE)
    clkbuf_instances = load_json(CLKBUF_FILE)
    pin_net_data = load_json(PIN_NET_FILE)
    net_names = load_json(NET_NAMES_FILE)

    pin_net_map = pin_net_data["pin_net_map"]

    # IMPORTANT: Stage 1 and Stage 1b each number instance_id independently,
    # both starting at 0 -- so a bare instance_id is NOT globally unique
    # (gate instance 0 and clkbuf instance 0 both exist). Every downstream
    # key in this script therefore uses the (cell_type, instance_id) TUPLE,
    # matching the convention Stage 6bc already relies on
    # (f"{cell_type}__{instance_id}"). Keying by instance_id alone would
    # silently merge unrelated gate/clkbuf instances that happen to share
    # a number -- this was a real bug in an earlier version of this script.

    # (cell_type, instance_id) -> cell_type  (trivial, but keeps lookups uniform)
    cell_type_by_instance = {}
    for inst in gate_instances:
        cell_type_by_instance[(inst["cell_type"], inst["instance_id"])] = inst["cell_type"]
    for inst in clkbuf_instances:
        cell_type_by_instance[(inst["cell_type"], inst["instance_id"])] = inst["cell_type"]

    # Build: net_id -> list of (instance_key, cell_type, pin_name)
    #        instance_key -> {pin_name: net_id}
    # where instance_key = (cell_type, instance_id)
    net_to_pins = defaultdict(list)
    instance_pins = defaultdict(dict)

    unmatched = 0
    for p in pin_net_map:
        net_id = p["net_id"]
        cell_type = p["cell_type"]
        inst_key = (cell_type, p["instance_id"])
        pin_name = p["pin_name"]
        if net_id is None:
            unmatched += 1
            continue
        net_to_pins[net_id].append((inst_key, cell_type, pin_name))
        instance_pins[inst_key][pin_name] = net_id

    print(f"Instances with pin data: {len(instance_pins)}")
    print(f"Nets with at least one pin: {len(net_to_pins)}")
    print(f"Unmatched pins (net_id=None): {unmatched}")

    graph = {
        "net_to_pins": {str(k): v for k, v in net_to_pins.items()},
        # instance_pins/cell_type_by_instance keys are (cell_type, instance_id)
        # tuples -- stringified as "('cell_type', instance_id)" for JSON.
        "instance_pins": {str(k): v for k, v in instance_pins.items()},
        "cell_type_by_instance": {str(k): v for k, v in cell_type_by_instance.items()},
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_GRAPH_FILE, "w") as f:
        json.dump(graph, f, indent=2)
    print(f"\n✓ Netlist graph saved to {OUTPUT_GRAPH_FILE}\n")

    return net_to_pins, instance_pins, cell_type_by_instance, net_names


def find_clk_net(net_names, net_to_pins):
    """Locate the clk net_id, cross-checking numeric id against name."""
    name_by_id = net_names  # {str(net_id): name}

    id_match = str(KNOWN_CLK_NET_ID) in name_by_id and name_by_id[str(KNOWN_CLK_NET_ID)] == KNOWN_CLK_NET_NAME
    name_matches = [nid for nid, name in name_by_id.items() if name == KNOWN_CLK_NET_NAME]

    if id_match:
        print(f"clk net confirmed: net_id={KNOWN_CLK_NET_ID}, name='{KNOWN_CLK_NET_NAME}'")
        return int(KNOWN_CLK_NET_ID)

    if len(name_matches) == 1:
        found_id = int(name_matches[0])
        print(f"⚠️ clk net_id has shifted since your last run.")
        print(f"   Expected net_id={KNOWN_CLK_NET_ID}, but name '{KNOWN_CLK_NET_NAME}' now maps to net_id={found_id}.")
        print(f"   Using net_id={found_id} (matched by name, not by id).")
        return found_id

    print(f"ERROR: could not confidently locate clk net.")
    print(f"  Looked for net_id={KNOWN_CLK_NET_ID} with name='{KNOWN_CLK_NET_NAME}'")
    print(f"  Name matches found: {name_matches}")
    print(f"  Re-run lookup_all_ports.py and update KNOWN_CLK_NET_ID/NAME in this script.")
    sys.exit(1)


def bfs_clock_tree(clk_net_id, net_to_pins, instance_pins, cell_type_by_instance):
    """
    BFS forward from the clk net through every clkbuf's A->X, following nets,
    until no more clkbuf instances can be traversed. Reports which flip-flop
    CLK pins were reached vs. not.
    """
    print(f"\n=== Clock Tree BFS from net_id={clk_net_id} ===\n")

    visited_nets = set()
    visited_clkbufs = set()
    reached_flipflop_clk_pins = set()  # {(cell_type, instance_id)} with CLK pin reached

    queue = deque([clk_net_id])
    visited_nets.add(clk_net_id)

    while queue:
        current_net = queue.popleft()
        pins_on_net = net_to_pins.get(current_net, [])

        for inst_key, cell_type, pin_name in pins_on_net:
            if is_clkbuf(cell_type):
                if pin_name == "A" and inst_key not in visited_clkbufs:
                    # Input reached -> this clkbuf now drives its output net
                    visited_clkbufs.add(inst_key)
                    x_net = instance_pins.get(inst_key, {}).get("X")
                    if x_net is not None and x_net not in visited_nets:
                        visited_nets.add(x_net)
                        queue.append(x_net)
            elif is_flipflop(cell_type):
                if pin_name == "CLK":
                    reached_flipflop_clk_pins.add(inst_key)

    # Now determine the FULL set of flip-flops and clkbufs in the design,
    # to compute what was NOT reached. Keys are (cell_type, instance_id).
    all_flipflops = {
        key for key, ct in cell_type_by_instance.items() if is_flipflop(ct)
    }
    all_clkbufs = {
        key for key, ct in cell_type_by_instance.items() if is_clkbuf(ct)
    }

    unreached_flipflops = all_flipflops - reached_flipflop_clk_pins
    unreached_clkbufs = all_clkbufs - visited_clkbufs

    print(f"Total flip-flops in design: {len(all_flipflops)}")
    print(f"Flip-flops with CLK reached from clk port: {len(reached_flipflop_clk_pins)}")
    print(f"Flip-flops NOT reached: {len(unreached_flipflops)}")
    print()
    print(f"Total clkbuf instances in design: {len(all_clkbufs)}")
    print(f"Clkbuf instances reached (input driven): {len(visited_clkbufs)}")
    print(f"Clkbuf instances NOT reached: {len(unreached_clkbufs)}")

    if unreached_flipflops:
        print(f"\nUnreached flip-flop instance IDs: {sorted(unreached_flipflops)}")
    if unreached_clkbufs:
        print(f"Unreached clkbuf instance IDs: {sorted(unreached_clkbufs)}")

    return {
        "all_flipflops": all_flipflops,
        "reached_flipflops": reached_flipflop_clk_pins,
        "unreached_flipflops": unreached_flipflops,
        "all_clkbufs": all_clkbufs,
        "reached_clkbufs": visited_clkbufs,
        "unreached_clkbufs": unreached_clkbufs,
    }


def cross_reference_output_generator(unreached_clkbufs, unreached_flipflops, cell_type_by_instance, footprints):
    if OUTPUT_GENERATOR_BBOX is None:
        print("\n(Skipping output-generator cross-check: OUTPUT_GENERATOR_BBOX not set.)")
        print("Fill in OUTPUT_GENERATOR_BBOX at the top of this script with the region's")
        print("(x0, y0, x1, y1) in chip coordinates to enable this check.")
        return

    x0, y0, x1, y1 = OUTPUT_GENERATOR_BBOX
    # Footprint entries carry cell_type alongside instance_id, so key by the
    # same (cell_type, instance_id) tuple as everywhere else in this script.
    fp_by_key = {(fp["cell_type"], fp["instance_id"]): fp["bbox"] for fp in footprints}

    def inside(inst_key):
        bbox = fp_by_key.get(inst_key)
        if bbox is None:
            return None
        bx0, by0, bx1, by1 = bbox
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        return x0 <= cx <= x1 and y0 <= cy <= y1

    print(f"\n=== Output-Generator Cross-Reference ===")
    print(f"Bounding box: ({x0}, {y0}) - ({x1}, {y1})\n")

    for label, ids in [("Unreached clkbufs", unreached_clkbufs), ("Unreached flip-flops", unreached_flipflops)]:
        in_region = [i for i in ids if inside(i)]
        out_region = [i for i in ids if inside(i) is False]
        unknown = [i for i in ids if inside(i) is None]
        print(f"{label}: {len(in_region)} inside region, {len(out_region)} outside, {len(unknown)} no footprint data")
        if out_region:
            print(f"  ⚠️ Outside instance IDs (worth a closer look): {sorted(out_region)}")


def main():
    net_to_pins, instance_pins, cell_type_by_instance, net_names = build_graph()
    clk_net_id = find_clk_net(net_names, net_to_pins)
    result = bfs_clock_tree(clk_net_id, net_to_pins, instance_pins, cell_type_by_instance)

    footprints = load_json(FOOTPRINT_FILE) if os.path.exists(FOOTPRINT_FILE) else []
    cross_reference_output_generator(
        result["unreached_clkbufs"], result["unreached_flipflops"], cell_type_by_instance, footprints
    )

    print("\n=== Summary ===")
    if result["unreached_flipflops"]:
        print("Some flip-flops are NOT reachable from the clk port. This explains the")
        print("all-X simulation output for at least those flops (and anything combinationally")
        print("downstream of them). Next: check whether they cluster in the output-generator")
        print("region (set OUTPUT_GENERATOR_BBOX above if not already), or inspect their")
        print("physical location directly in KLayout.")
    else:
        print("All flip-flops ARE reachable from clk. If simulation is still all-X, the")
        print("clock tree is not the cause -- revisit testbench timing (reset deassertion,")
        print("clock generation delays) instead.")


if __name__ == "__main__":
    main()