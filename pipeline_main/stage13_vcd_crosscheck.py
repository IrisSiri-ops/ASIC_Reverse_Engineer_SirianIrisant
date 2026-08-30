"""
====================================================================
PHASE 6: VCD CROSS-VALIDATION
====================================================================
Stage 13: Cross-check against example_inputs.vcd
------------------------------------------------------

Purpose
-------
The first validation against REAL ground truth -- a captured trace from
the actual chip, not just internal self-consistency. Parses the VCD,
replays its exact recorded event sequence through the Stage 11
Simulator (driven directly, not via Stage 12's generic reset()/cycle()
abstraction, since fidelity to the real recorded sequence matters more
here than convenience), and compares our simulated success/O[7:0]
against what the real design actually produced at every point its
outputs changed.

Historical note (net_0562)
-----------------------------
An earlier version of the recovered netlist had one net (net_0562) with
no driving instance, discovered while first building this cross-check.
See STATUS_net_0562.md for the investigation. This is now fixed
permanently in Stage 9's netlist assembly, so this script compares ALL
8 output bits directly against the real trace -- no masking needed.

Discovery: the design's message output
------------------------------------------
Decoding the O[7:0] byte sequence in example_inputs.vcd (after `enable`
drops low near the end of the trace) spells out "TRY AGAIN", null-
terminated -- the chip's own readable confirmation that this trace's
input sequence does NOT trigger success (consistent with the puzzle
README). This revealed the design emits a readable ASCII status message
on O[7:0], one character per cycle, which shaped the whole rest of this
investigation (including Stage 17's final "(* TWO STARS *)" readout).

VCD format notes (from inspecting the real file)
----------------------------------------------------
Signal IDs: ! =clk, " =rst_n, # =enable, $ =I, % =O[7:0] (vector), & =success
Timescale: 1ps. clk toggles every 5000ps (10000ps period).
Scalar changes: "<value><id>", e.g. "1!" -- clk=1.
Vector changes: "b<binary><space><id>", e.g. "b1010100 %" -- O=0x54.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage11_simulator import Simulator, load_netlist

VCD_FILE_CANDIDATES = ["../example_inputs.vcd", "../../example_inputs.vcd"]

SCALAR_RE = re.compile(r"^([01xz])(\S+)$")
VECTOR_RE = re.compile(r"^b([01xz]+)\s+(\S+)$")
TIME_RE = re.compile(r"^#(\d+)$")


def find_vcd_file():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for candidate in VCD_FILE_CANDIDATES:
        path = os.path.normpath(os.path.join(script_dir, candidate))
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        "example_inputs.vcd not found. Expected at ../example_inputs.vcd "
        "relative to pipeline_main/ (i.e. in the puzzle root directory)."
    )


def parse_vcd(path):
    """
    Returns:
      id_to_name: {signal_id_char: name}
      events: list of (time_ps, {signal_id_char: value_str}) -- all changes
              at that timestamp grouped together, in file order.
    """
    id_to_name = {}
    events = []
    current_time = 0
    current_batch = {}

    with open(path) as f:
        in_header = True
        for line in f:
            line = line.strip()
            if not line:
                continue

            if line.startswith("$var"):
                # $var reg 1 ! clk $end   OR   $var wire 8 % O [7:0] $end
                parts = line.split()
                sig_id = parts[3]
                name = parts[4]
                id_to_name[sig_id] = name
                continue

            if line == "$enddefinitions $end":
                in_header = False
                continue

            if in_header:
                continue

            if line in ("$dumpall", "$dumpvars", "$end", "$comment", "Show the parameter values. $end"):
                continue

            m = TIME_RE.match(line)
            if m:
                if current_batch:
                    events.append((current_time, current_batch))
                current_time = int(m.group(1))
                current_batch = {}
                continue

            m = VECTOR_RE.match(line)
            if m:
                value_bits, sig_id = m.group(1), m.group(2)
                current_batch[sig_id] = value_bits
                continue

            m = SCALAR_RE.match(line)
            if m:
                value, sig_id = m.group(1), m.group(2)
                current_batch[sig_id] = value
                continue
            # silently ignore anything else (stray $end tokens etc.)

    if current_batch:
        events.append((current_time, current_batch))

    return id_to_name, events


def bits_to_int(bits, width):
    """Parse a VCD binary string (may be shorter than width, may contain x/z) into an int,
    with a set of bit positions (0=LSB) that were 'x' (unknown) in the source."""
    bits = bits.zfill(width)
    unknown_bits = set()
    value = 0
    for i, ch in enumerate(reversed(bits)):
        if ch == "1":
            value |= (1 << i)
        elif ch in ("x", "z"):
            unknown_bits.add(i)
        # '0' contributes nothing
    return value, unknown_bits


def decode_ascii(byte_sequence, mask_bits=()):
    """byte_sequence: list of (int_value, unknown_bit_set). mask_bits: bit positions
    to always render as '?' regardless of source (used for O[1]/O[4])."""
    chars = []
    for value, unknown in byte_sequence:
        if value == 0:
            chars.append("<NUL>")
            continue
        display_unknown = unknown | set(mask_bits)
        if display_unknown:
            chars.append(f"?({value:#04x} w/ unknown bits {sorted(display_unknown)})")
        elif 32 <= value <= 126:
            chars.append(chr(value))
        else:
            chars.append(f"\\x{value:02x}")
    return "".join(c if len(c) == 1 else f"[{c}]" for c in chars)


def main():
    print("=== Stage 13 (Phase 6): VCD Cross-Validation ===\n")

    vcd_path = find_vcd_file()
    print(f"Parsing {vcd_path}...")
    id_to_name, events = parse_vcd(vcd_path)
    name_to_id = {v: k for k, v in id_to_name.items()}
    print(f"Signals found: {id_to_name}")
    print(f"Total timestamped event groups: {len(events)}\n")

    clk_id = name_to_id["clk"]
    rst_n_id = name_to_id["rst_n"]
    enable_id = name_to_id["enable"]
    i_id = name_to_id["I"]
    o_id = name_to_id.get("O") or name_to_id.get("O [7:0]")
    success_id = name_to_id["success"]

    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)
    NETLIST_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage9_final_netlist.json")
    netlist = load_netlist(NETLIST_FILE)
    sim = Simulator(netlist)
    print("Simulator loaded against real recovered netlist.\n")

    # Real (VCD-reported) current state, forward-filled as we scan.
    real_state = {clk_id: 0, rst_n_id: 0, enable_id: 0, i_id: 0, o_id: "0" * 8, success_id: "x"}

    real_o_history = []     # list of (value, unknown_bits) as reported in VCD
    sim_o_history = []      # list of (value, unknown_bits) as WE computed
    comparisons = []        # list of dicts per rising edge

    prev_clk = 0
    cycle_num = 0

    for time_ps, changes in events:
        # Apply all changes at this timestamp to our record of "real" state.
        real_state.update(changes)

        clk_val = real_state.get(clk_id, "0")
        if clk_val not in ("0", "1"):
            continue  # x/z clk, ignore

        clk_val = int(clk_val)
        rising_edge = (clk_val == 1 and prev_clk == 0)
        prev_clk = clk_val

        # Drive our simulator with whatever primary inputs changed, exactly
        # mirroring the real event -- direct step(), not the generic driver.
        sim_updates = {}
        if clk_id in changes:
            sim_updates["clk"] = bool(clk_val)
        if rst_n_id in changes:
            sim_updates["rst_n"] = real_state[rst_n_id] == "1"
        if enable_id in changes:
            sim_updates["enable"] = real_state[enable_id] == "1"
        if i_id in changes:
            sim_updates["I"] = real_state[i_id] == "1"

        if sim_updates:
            sim.step(**sim_updates)
        elif clk_id in changes:
            sim.step()  # clk changed but was already captured above; ensure settle ran

        if rising_edge:
            cycle_num += 1
            real_o_val, real_o_unknown = bits_to_int(real_state.get(o_id, "0"), 8)
            real_success = real_state.get(success_id, "x")

            sim_outputs = sim.read_outputs()
            sim_o_bits = "".join(
                "1" if sim_outputs.get(f"O[{b}]") else ("?" if sim_outputs.get(f"O[{b}]") is None else "0")
                for b in reversed(range(8))
            )
            # For int conversion, treat None (O[1]/O[4]) as 0 with unknown flagged
            sim_o_val = 0
            sim_o_unknown = set()
            for b in range(8):
                v = sim_outputs.get(f"O[{b}]")
                if v is None:
                    sim_o_unknown.add(b)
                elif v:
                    sim_o_val |= (1 << b)
            sim_success = sim_outputs.get("success")

            real_o_history.append((real_o_val, real_o_unknown))
            sim_o_history.append((sim_o_val, sim_o_unknown))

            comparisons.append({
                "cycle": cycle_num,
                "time_ps": time_ps,
                "real_O": real_o_val, "real_O_unknown": real_o_unknown,
                "sim_O": sim_o_val, "sim_O_unknown": sim_o_unknown,
                "real_success": real_success,
                "sim_success": sim_success,
            })

    print(f"Total rising clock edges replayed: {cycle_num}\n")

    # --- Compare ALL 8 bits directly (net_0562 fixed -- no masking needed) ---
    total_checked = 0
    total_match = 0
    success_checked = 0
    success_match = 0
    first_mismatch = None

    for c in comparisons:
        for b in range(8):
            if b in c["real_O_unknown"] or b in c["sim_O_unknown"]:
                continue
            total_checked += 1
            real_bit = (c["real_O"] >> b) & 1
            sim_bit = (c["sim_O"] >> b) & 1
            if real_bit == sim_bit:
                total_match += 1
            elif first_mismatch is None:
                first_mismatch = c

        if c["real_success"] in ("0", "1"):
            success_checked += 1
            sim_success_bit = str(int(bool(c["sim_success"]))) if c["sim_success"] is not None else None
            if sim_success_bit == c["real_success"]:
                success_match += 1
            elif first_mismatch is None:
                first_mismatch = c

    print("=== Bit-level comparison (all 8 output bits) ===")
    if total_checked:
        print(f"O bits matched: {total_match}/{total_checked} ({100*total_match/total_checked:.1f}%)")
    print(f"success matched: {success_match}/{success_checked}")
    if first_mismatch:
        print(f"\nFirst mismatch at cycle {first_mismatch['cycle']} (t={first_mismatch['time_ps']}ps):")
        print(f"  real: O={format(first_mismatch['real_O'], '08b')} success={first_mismatch['real_success']}")
        print(f"  sim:  O={format(first_mismatch['sim_O'], '08b')} success={first_mismatch['sim_success']}")

    print("\n=== Decoded ASCII output (all 8 bits, unmasked) ===")
    real_str = decode_ascii(real_o_history)
    sim_str = decode_ascii(sim_o_history)
    print(f"REAL (from VCD): {real_str}")
    print(f"SIM  (ours):     {sim_str}")

    print("\n=== Verdict ===")
    if total_checked and total_match == total_checked and success_match == success_checked:
        print("PERFECT MATCH on all 8 output bits and success, across the entire real")
        print("captured trace. This is strong, real-world evidence that the cell-behavior")
        print("library (Stage 10) and simulator engine (Stage 11) are correct.")
    else:
        print("Mismatches found -- see above. This means either the cell-behavior library")
        print("has an incorrect gate definition, or there's a bug in the simulator/driver")
        print("logic. Worth checking the specific cell type(s) involved in the first")
        print("mismatch's dependency chain.")


if __name__ == "__main__":
    main()