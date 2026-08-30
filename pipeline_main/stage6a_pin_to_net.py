import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

METAL_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage4_routing_geometry.json")
NETS_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage5_nets.json")
PINS_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage3_absolute_pins.json")
CLKBUF_PINS_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1b_clkbuf_pins.json")
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage6a_pin_net_map.json")

POWER_PINS = {"VPWR", "VGND", "VPB", "VNB"}


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
    print("=== PUZZLE STAGE 6a: Pin-to-Net Assignment ===\n")

    with open(METAL_FILE) as f:
        metal = json.load(f)
    with open(NETS_FILE) as f:
        nets = json.load(f)
    with open(PINS_FILE) as f:
        pin_data = json.load(f)
    with open(CLKBUF_PINS_FILE) as f:
        pin_data = pin_data + json.load(f)

    rect_to_net = {}
    for net_id, net in enumerate(nets):
        for m in net["members"]:
            rect_to_net[(m["layer"], m["index"])] = net_id

    pin_net_map = []
    unmatched = 0

    for inst in pin_data:
        for pin_name, info in inst["pins"].items():
            px, py = info["position"]
            layer = info["layer_name"]
            found_net = None
            if layer in metal:
                for idx, poly in enumerate(metal[layer]):
                    if point_in_polygon(px, py, poly):
                        found_net = rect_to_net.get((layer, idx))
                        break

            pin_net_map.append({
                "instance_id": inst["instance_id"],
                "cell_type": inst["cell_type"],
                "pin_name": pin_name,
                "net_id": found_net,
                "is_power": pin_name in POWER_PINS,
            })
            if found_net is None:
                unmatched += 1

    total = len(pin_net_map)
    print(f"Total pins: {total}")
    print(f"Matched: {total - unmatched} ({100*(total-unmatched)/total:.1f}%)")
    print(f"Unmatched: {unmatched}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump({"pin_net_map": pin_net_map}, f, indent=2)
    print(f"\n✓ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
