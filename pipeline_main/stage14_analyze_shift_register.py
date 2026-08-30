"""
====================================================================
PHASE 7: SEARCH FOR THE SUCCESS-TRIGGERING INPUT
====================================================================
Stage 14: Shift-Register Structure Analysis
------------------------------------------------

Purpose
-------
Before brute-forcing an unknown-length input sequence, determine the
ACTUAL width of the shift register that I feeds into. Brute force is
only feasible if this number is small (roughly <=24 bits in pure
Python within reasonable time); if it's large, we need a smarter
search (Phase 7b, symbolic/SAT-based) instead of blind brute force.

Basis for this trace
----------------------
Reviewing puzzle_final.v earlier showed net_0001 (derived from enable)
selecting on a large number of mux2_1 instances, with the FIRST one
having A1(I) directly -- the standard "shift new bit in when enabled"
pattern:  D <- enable ? new_bit : hold_current_Q

This traces that chain: start at I, find the mux2_1 consuming it via
A1, follow to the flip-flop it feeds (D pin), take that flip-flop's Q
output, and repeat -- finding the NEXT mux2_1 stage that consumes THAT
Q via A1. This directly measures the shift register's real depth from
netlist structure, not guesswork.
"""

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage10_cell_library import COMB_CELLS, SEQ_CELLS

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)
NETLIST_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage9_final_netlist.json")


def base_name(cell_type):
    prefix = "sky130_fd_sc_hd__"
    return cell_type[len(prefix):] if cell_type.startswith(prefix) else cell_type


def main():
    print("=== Stage 14: Shift-Register Structure Analysis ===\n")

    with open(NETLIST_FILE) as f:
        netlist = json.load(f)

    instances = netlist["instances"]
    ports = netlist["ports"]

    # net_name -> list of (cell_type, instance_id, pin_name) for every pin referencing it
    net_to_pins = defaultdict(list)
    # (cell_type, instance_id) -> {pin_name: net_name}
    instance_pins = {}

    for inst in instances:
        key = (inst["cell_type"], inst["instance_id"])
        instance_pins[key] = inst["pins"]
        for pin_name, net_name in inst["pins"].items():
            net_to_pins[net_name].append((inst["cell_type"], inst["instance_id"], pin_name))

    i_net = ports["I"]["net_name"]
    print(f"Starting trace from I's net: '{i_net}'\n")

    chain = []
    visited_nets = set()
    current_net = i_net

    while True:
        # Find mux2_1 instance(s) consuming current_net via A1 (the "new bit" input,
        # per the confirmed pattern from puzzle_final.v's first stage: A1(I)).
        mux_candidates = [
            (ct, iid) for (ct, iid, pin) in net_to_pins.get(current_net, [])
            if base_name(ct) == "mux2_1" and pin == "A1"
        ]

        if not mux_candidates:
            print(f"Chain ends: no mux2_1 consumes '{current_net}' via A1.")
            break

        if len(mux_candidates) > 1:
            print(f"WARNING: multiple mux2_1 candidates found consuming '{current_net}' "
                  f"via A1: {mux_candidates}. Taking the first; verify this is correct.")

        mux_ct, mux_iid = mux_candidates[0]
        mux_output_net = instance_pins[(mux_ct, mux_iid)].get("X")
        if mux_output_net is None:
            print(f"WARNING: mux2_1 instance {mux_iid} has no 'X' output pin recorded.")
            break

        # Find the flip-flop whose D pin is driven by this mux's output.
        ff_candidates = []
        for ct, iid, pin in net_to_pins.get(mux_output_net, []):
            base = base_name(ct)
            if base in SEQ_CELLS and pin == SEQ_CELLS[base]["D"]:
                ff_candidates.append((ct, iid, base))

        if not ff_candidates:
            print(f"Chain ends: mux2_1 instance {mux_iid}'s output '{mux_output_net}' "
                  f"doesn't feed any flip-flop's D pin.")
            break

        if len(ff_candidates) > 1:
            print(f"WARNING: multiple flip-flops driven by '{mux_output_net}': {ff_candidates}. "
                  f"Taking the first.")

        ff_ct, ff_iid, ff_base = ff_candidates[0]
        q_net = instance_pins[(ff_ct, ff_iid)].get(SEQ_CELLS[ff_base]["Q"])

        chain.append({
            "stage": len(chain) + 1,
            "mux_instance": f"{mux_ct} (id={mux_iid})",
            "flipflop_instance": f"{ff_ct} (id={ff_iid})",
            "q_net": q_net,
        })

        print(f"  Stage {len(chain):3d}: mux2_1(id={mux_iid}) -> {ff_ct}(id={ff_iid}) -> Q='{q_net}'")

        if q_net in visited_nets:
            print(f"\nWARNING: '{q_net}' already visited -- cycle detected, stopping to avoid infinite loop.")
            break
        visited_nets.add(q_net)
        current_net = q_net

    print(f"\n=== Result ===")
    print(f"Shift register chain length: {len(chain)} stages")

    if len(chain) == 0:
        print("\nNo chain found at all -- the A1-consumption assumption may be wrong,")
        print("or I feeds into the design differently than expected. Worth manually")
        print("checking net_to_pins for the I net directly.")
    elif len(chain) <= 24:
        print(f"\nThis is SMALL ENOUGH for direct brute force (2^{len(chain)} = "
              f"{2**len(chain):,} combinations). Proceeding to Stage 15 (brute-force "
              f"search) is reasonable.")
    else:
        print(f"\nThis is TOO LARGE for brute force (2^{len(chain)} = "
              f"{2**len(chain):,} combinations -- infeasible in reasonable time).")
        print("A smarter search (symbolic/SAT-based, Phase 7's 'Path D' fallback")
        print("discussed earlier) would be needed instead of blind enumeration.")

    # Save the chain for Stage 15 to consume directly, so it doesn't need to
    # re-derive this structure.
    output_file = os.path.join(PUZZLE_DIR, "output_main", "stage14_shift_chain.json")
    with open(output_file, "w") as f:
        json.dump(chain, f, indent=2)
    print(f"\n✓ Chain saved to {output_file}")


if __name__ == "__main__":
    main()