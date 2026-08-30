import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

PIN_NET_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage6a_pin_net_map.json")
OUTPUT_VERILOG = os.path.join(PUZZLE_DIR, "output_main", "recovered_netlist.v")
OUTPUT_MAP = os.path.join(PUZZLE_DIR, "output_main", "stage6b_net_names.json")


def main():
    print("=== PUZZLE STAGE 6b/6c: Net Naming & Netlist Emission ===\n")

    with open(PIN_NET_FILE) as f:
        data = json.load(f)
    pin_net_map = data["pin_net_map"]

    net_to_pins = {}
    for p in pin_net_map:
        if p["net_id"] is None:
            continue
        net_to_pins.setdefault(p["net_id"], []).append(p)

    power_nets = {}
    for net_id, pins in net_to_pins.items():
        names = set(p["pin_name"] for p in pins)
        if names == {"VPWR"}:
            power_nets["VPWR"] = net_id
        elif names == {"VGND"}:
            power_nets["VGND"] = net_id

    print(f"Power nets identified: {power_nets}")

    net_names = {}
    if "VPWR" in power_nets:
        net_names[power_nets["VPWR"]] = "VPWR"
    if "VGND" in power_nets:
        net_names[power_nets["VGND"]] = "VGND"

    port_counter = 1
    signal_counter = 1
    for net_id, pins in sorted(net_to_pins.items()):
        if net_id in net_names:
            continue
        if len(pins) == 1:
            net_names[net_id] = f"port_candidate_{port_counter:02d}"
            port_counter += 1
        else:
            net_names[net_id] = f"net_{signal_counter:04d}"
            signal_counter += 1

    print(f"Named nets: {len(net_names)} total")
    print(f"  Power: 2, Port candidates: {port_counter-1}, Internal: {signal_counter-1}")

    with open(OUTPUT_MAP, "w") as f:
        json.dump({str(k): v for k, v in net_names.items()}, f, indent=2)

    instances = {}
    for p in pin_net_map:
        if p["net_id"] is None:
            continue
        key = f"{p['cell_type']}__{p['instance_id']}"
        if key not in instances:
            instances[key] = {"cell_type": p["cell_type"], "pins": {}}
        instances[key]["pins"][p["pin_name"]] = net_names[p["net_id"]]

    lines = []
    lines.append("// Recovered netlist -- puzzle.gds -- extracted purely from GDS geometry")
    lines.append("module puzzle_recovered (")
    lines.append("    // top-level ports unresolved -- see port_candidate_* wires")
    lines.append(");\n")
    lines.append("  wire VPWR, VGND;")
    for i in range(1, signal_counter):
        lines.append(f"  wire net_{i:04d};")
    for i in range(1, port_counter):
        lines.append(f"  wire port_candidate_{i:02d};")
    lines.append("")

    for key in sorted(instances.keys()):
        inst = instances[key]
        cell_type = inst["cell_type"]
        pins = inst["pins"]
        inst_name = key.replace("/", "_")
        pin_str = ", ".join(f".{pin}({net})" for pin, net in sorted(pins.items()))
        lines.append(f"  {cell_type} {inst_name} ( {pin_str} );\n")

    lines.append("endmodule")

    with open(OUTPUT_VERILOG, "w") as f:
        f.write("\n".join(lines))

    print(f"\nTotal instances emitted: {len(instances)}")
    print(f"✓ Verilog saved to {OUTPUT_VERILOG}")


if __name__ == "__main__":
    main()
