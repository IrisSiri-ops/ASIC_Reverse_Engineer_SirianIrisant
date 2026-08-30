"""
====================================================================
PHASE 2: FINAL NETLIST ASSEMBLY (v2 -- net_0562 fix applied)
====================================================================
Stage 9: Final Netlist Assembly
----------------------------------

Changes from v1
-----------------
Applies the confirmed fix for net_0562 (see STATUS_net_0562.md for the
full investigation): merges net_0562 with the net driven by
sky130_fd_sc_hd__nor3_2 instance 485.

Evidence for this specific fix:
  1. KLayout's independent connectivity extraction (used purely as a
     debugging cross-check, not part of the shipped pipeline) found
     net_0562's true net includes a nor3_2 pin and an and2_2 pin that
     our own extraction never captured.
  2. All 21 candidate merges (4 nor3_2 + 17 and2_2 instances) were
     tested against the real captured "TRY AGAIN" VCD trace: all passed
     (uninformative on its own, since that trace didn't happen to
     exercise net_0562's logic term).
  3. All 21 candidates were tested against the winning success-
     triggering input sequence found via Stage 16's symbolic search:
     ALL 21 converged on the exact same decoded message,
     "(* TWO STARS *)" -- strong convergent evidence this is correct,
     though not a proof that isolates one single physically-true net.
  4. nor3_2 instance 485 is used as the specific fix applied here,
     since it was one of the two cell types KLayout's independent
     extraction specifically flagged as belonging to net_0562's true
     net (the and2_2 candidates matched numerically but had no
     independent structural evidence pointing at any specific instance
     among the 17).

This is documented as evidence-based but NOT a mathematically unique
proof -- if net_0562 is revisited later, this is the place to start.
"""

import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PUZZLE_DIR, "output_main")

GRAPH_FILE = os.path.join(OUTPUT_DIR, "stage7_netlist_graph.json")
PORT_MAP_FILE = os.path.join(OUTPUT_DIR, "stage8_port_map.json")
NET_NAMES_FILE = os.path.join(OUTPUT_DIR, "stage6b_net_names.json")

OUTPUT_JSON = os.path.join(OUTPUT_DIR, "stage9_final_netlist.json")
OUTPUT_VERILOG = os.path.join(OUTPUT_DIR, "puzzle_final.v")

PORT_DIRECTIONS = {
    "clk": "input", "rst_n": "input", "enable": "input", "I": "input",
    "success": "output",
    "O[0]": "output", "O[1]": "output", "O[2]": "output", "O[3]": "output",
    "O[4]": "output", "O[5]": "output", "O[6]": "output", "O[7]": "output",
}

NET_0562_FIX_TARGET_CELL_TYPE = "sky130_fd_sc_hd__nor3_2"
NET_0562_FIX_TARGET_INSTANCE_ID = 485
NET_0562_FIX_TARGET_OUTPUT_PIN = "Y"


def load_json(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing required input: {path}")
    with open(path) as f:
        return json.load(f)


def parse_tuple_key(key_str):
    inner = key_str.strip("()")
    parts = [p.strip().strip("'").strip('"') for p in inner.split(",")]
    cell_type = parts[0]
    instance_id = int(parts[1])
    return (cell_type, instance_id)


def main():
    print("=== PUZZLE STAGE 9 v2 (Phase 2: Final Netlist Assembly, net_0562 fix applied) ===\n")

    graph = load_json(GRAPH_FILE)
    port_map = load_json(PORT_MAP_FILE)
    net_names_raw = load_json(NET_NAMES_FILE) if os.path.exists(NET_NAMES_FILE) else {}

    instance_pins_raw = graph["instance_pins"]
    cell_type_by_instance_raw = graph["cell_type_by_instance"]

    instance_pins = {parse_tuple_key(k): v for k, v in instance_pins_raw.items()}
    cell_type_by_instance = {parse_tuple_key(k): v for k, v in cell_type_by_instance_raw.items()}

    print(f"Instances loaded: {len(instance_pins)}")
    print(f"Ports loaded: {len(port_map)} / {len(PORT_DIRECTIONS)} expected")

    missing_ports = set(PORT_DIRECTIONS.keys()) - set(port_map.keys())
    if missing_ports:
        print(f"WARNING: Missing port mappings: {missing_ports}")

    fix_key = (NET_0562_FIX_TARGET_CELL_TYPE, NET_0562_FIX_TARGET_INSTANCE_ID)
    if fix_key not in instance_pins:
        print(f"WARNING: fix target instance {fix_key} not found -- fix NOT applied.")
    else:
        target_net_id = instance_pins[fix_key].get(NET_0562_FIX_TARGET_OUTPUT_PIN)
        if target_net_id is None:
            print(f"WARNING: fix target instance has no '{NET_0562_FIX_TARGET_OUTPUT_PIN}' "
                  f"pin recorded -- fix NOT applied.")
        else:
            driven_net_ids = set()
            referenced_net_ids = set()
            for (ct, iid), pins in instance_pins.items():
                for pin, net_id in pins.items():
                    referenced_net_ids.add(net_id)
            for (ct, iid), pins in instance_pins.items():
                for pin, net_id in pins.items():
                    if pin in ("X", "Y", "Q", "HI", "LO"):
                        driven_net_ids.add(net_id)

            output_port_names = {"success"} | {f"O[{i}]" for i in range(8)}
            input_port_net_ids = {
                info["net_id"] for name, info in port_map.items()
                if name not in output_port_names
            }
            # Power net ids: detect directly rather than relying on naming
            # done later in the script -- any net referenced via a VPWR/VGND
            # pin name is a power net, never "driven" by a gate output.
            vpwr_vgnd_candidates = set()
            for (ct, iid), pins in instance_pins.items():
                for pin, net_id in pins.items():
                    if pin in ("VPWR", "VGND"):
                        vpwr_vgnd_candidates.add(net_id)

            excluded_ids = input_port_net_ids | vpwr_vgnd_candidates
            undriven = (referenced_net_ids - driven_net_ids) - excluded_ids

            if len(undriven) != 1:
                print(f"WARNING: expected exactly 1 undriven net, found {len(undriven)}: "
                      f"{undriven}. Fix NOT applied automatically -- verify manually.")
            else:
                net_0562_id = undriven.pop()
                print(f"Applying net_0562 fix: merging net_id={net_0562_id} into "
                      f"net_id={target_net_id} (driven by {fix_key})")
                merge_count = 0
                for (ct, iid), pins in instance_pins.items():
                    for pin in list(pins.keys()):
                        if pins[pin] == net_0562_id:
                            pins[pin] = target_net_id
                            merge_count += 1
                print(f"  {merge_count} pin references updated.\n")

    port_net_ids = {info["net_id"]: name for name, info in port_map.items()}
    net_name_by_id = dict(port_net_ids)

    for net_id_str, name in net_names_raw.items():
        net_id = int(net_id_str)
        if name in ("VPWR", "VGND") and net_id not in net_name_by_id:
            net_name_by_id[net_id] = name

    all_net_ids = set()
    for pins in instance_pins.values():
        all_net_ids.update(pins.values())

    remaining_ids = sorted(nid for nid in all_net_ids if nid not in net_name_by_id)
    for i, net_id in enumerate(remaining_ids, start=1):
        net_name_by_id[net_id] = f"net_{i:04d}"

    print(f"Total distinct nets referenced by instance pins: {len(all_net_ids)}")
    print(f"  Named as real ports: {len(port_net_ids)}")
    print(f"  Named as power (VPWR/VGND): {sum(1 for n in net_name_by_id.values() if n in ('VPWR','VGND'))}")
    print(f"  Named as net_XXXX: {len(remaining_ids)}")

    instances_out = []
    for (cell_type, instance_id), pins in sorted(instance_pins.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        pin_nets = {pin_name: net_name_by_id[net_id] for pin_name, net_id in pins.items()}
        instances_out.append({
            "cell_type": cell_type, "instance_id": instance_id, "pins": pin_nets,
        })

    final_netlist = {
        "ports": {
            name: {"net_id": info["net_id"], "net_name": name, "direction": PORT_DIRECTIONS[name]}
            for name, info in port_map.items()
        },
        "nets": {str(nid): name for nid, name in sorted(net_name_by_id.items())},
        "instances": instances_out,
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(final_netlist, f, indent=2)
    print(f"\n✓ Final netlist JSON saved to {OUTPUT_JSON}")

    lines = []
    lines.append("// Final recovered netlist -- puzzle.gds -- ports resolved via Stage 8 label lookup")
    lines.append("// net_0562 fix applied: merged with nor3_2 instance 485's output (see docstring)")
    lines.append("module puzzle_recovered (")
    port_lines = []
    for name in ["clk", "rst_n", "enable", "I", "success"] + [f"O[{i}]" for i in range(8)]:
        if name in port_map:
            direction = PORT_DIRECTIONS[name]
            verilog_name = name.replace("[", "_").replace("]", "")
            port_lines.append(f"    {direction} {verilog_name}")
    lines.append(",\n".join(port_lines))
    lines.append(");\n")

    port_net_id_set = set(port_net_ids.keys())
    for net_id, name in sorted(net_name_by_id.items()):
        if net_id in port_net_id_set:
            continue
        lines.append(f"  wire {name};")
    lines.append("")

    for inst in instances_out:
        inst_name = f"{inst['cell_type']}__{inst['instance_id']}".replace("sky130_fd_sc_hd__", "")
        pin_str = ", ".join(f".{pin}({net})" for pin, net in sorted(inst["pins"].items()))
        lines.append(f"  {inst['cell_type']} {inst_name} ( {pin_str} );\n")

    lines.append("endmodule")

    with open(OUTPUT_VERILOG, "w") as f:
        f.write("\n".join(lines))
    print(f"✓ Human-readable Verilog saved to {OUTPUT_VERILOG}")


if __name__ == "__main__":
    main()