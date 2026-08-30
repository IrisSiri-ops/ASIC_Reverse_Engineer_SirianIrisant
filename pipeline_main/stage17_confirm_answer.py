"""
Stage 17: Confirm and Display the Final Answer
====================================================

Purpose
-------
Stage 16 finds the winning input symbolically and saves it to
stage16_sat_result.json, but doesn't itself confirm it concretely or
decode the message -- that previously required manually running a
separate verification script after the pipeline finished. This folds
that confirmation into the pipeline itself as its true final stage, so
a full run of run_pipeline.py ends with the actual answer printed
clearly, not just a bit sequence.

Replays the winning sequence through the concrete Simulator (against
the now-fixed netlist, net_0562 merge included) and prints a clean
final summary: the input, the cycle success triggers, and the decoded
message.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage11_simulator import Simulator, load_netlist

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)
NETLIST_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage9_final_netlist.json")
SAT_RESULT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage16_sat_result.json")

M_OBSERVE_CYCLES = 60  # generous margin; message is well within this


def decode_ascii(byte_list):
    chars = []
    for v in byte_list:
        if v == 0:
            chars.append(".")
        elif 32 <= v <= 126:
            chars.append(chr(v))
        else:
            chars.append(f"[{v:02x}]")
    return "".join(chars)


def decode_message_only(byte_list):
    """Just the message text, stopping at the first NUL terminator --
    for a clean, human-readable final answer line."""
    out = []
    for v in byte_list:
        if v == 0:
            break
        if 32 <= v <= 126:
            out.append(chr(v))
        else:
            out.append(f"[{v:02x}]")
    return "".join(out)


def main():
    print("=== Stage 17: Confirm and Display the Final Answer ===\n")

    if not os.path.exists(SAT_RESULT_FILE):
        print("stage16_sat_result.json not found -- Stage 16 must run (and find SAT)")
        print("before this stage can confirm anything. Nothing to do.")
        return

    with open(SAT_RESULT_FILE) as f:
        result = json.load(f)
    bits = result["bits"]

    netlist = load_netlist(NETLIST_FILE)
    sim = Simulator(netlist)

    sim.step(rst_n=False, clk=False, enable=False, I=False)
    sim.step(rst_n=True, clk=False)

    success_cycle = None
    output_bytes = []
    cycle = 0

    for bit in bits:
        cycle += 1
        sim.step(enable=True, I=bool(bit), clk=True)
        if sim.read("success") and success_cycle is None:
            success_cycle = cycle
        sim.step(clk=False)

    for _ in range(M_OBSERVE_CYCLES):
        cycle += 1
        sim.step(enable=False, I=False, clk=True)
        if sim.read("success") and success_cycle is None:
            success_cycle = cycle
        outputs = sim.read_outputs()
        byte_val = 0
        for b in range(8):
            v = outputs.get(f"O[{b}]")
            if v:
                byte_val |= (1 << b)
        output_bytes.append(byte_val)
        sim.step(clk=False)

    message = decode_message_only(output_bytes)

    print("=" * 60)
    print("FINAL ANSWER")
    print("=" * 60)
    print(f"Input sequence ({len(bits)} bits): {''.join(str(b) for b in bits)}")
    print(f"success triggers at cycle: {success_cycle}")
    print(f"Decoded message: {message}")
    print("=" * 60)

    if success_cycle is None:
        print("\nWARNING: success did NOT trigger with this input against the current")
        print("netlist. This would mean something changed since the answer was found --")
        print("worth investigating rather than trusting stage16_sat_result.json blindly.")


if __name__ == "__main__":
    main()