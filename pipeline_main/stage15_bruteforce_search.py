"""
Stage 15 (v2): Brute-Force Search for the Success-Triggering Input
====================================================================

Purpose
-------
Corrected version, based on Stage 15b's findings from real VCD ground
truth:

  1. DURATION: real hardware held enable high for 121 cycles before its
     first evaluation (output/success only becomes live after that many
     cycles) -- not just the 12 cycles matching the shift register's
     depth, which is what the original v1 search (incorrectly) used.
     This version pads with 113 arbitrary cycles (I=0) before feeding
     the actual 12-bit candidate in the final 12 cycles, for 125 total
     enable-high cycles (121 + small safety margin).

  2. BIT ORDERING: Stage 15b confirmed stage 1 holds the MOST RECENTLY
     shifted-in bit (ordinary shift-register behavior). More importantly,
     trying a candidate value's bits in either MSB-first or LSB-first
     feed order are just two different labelings of the SAME set of
     4,096 possible final register contents -- either alone already
     gives full, non-redundant coverage. So this version only needs ONE
     ordering (MSB-first, arbitrarily), halving the original 8,192-trial
     search down to 4,096 trials.

Protocol per trial
--------------------
  reset() -> 113 cycles (enable=True, I=0, padding) -> 12 cycles
  (enable=True, I=candidate bit) -> 30 extra cycles (enable=False) to
  observe success/output. success checked at every single cycle
  throughout.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage11_simulator import Simulator, load_netlist

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)
NETLIST_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage9_final_netlist.json")
SHIFT_CHAIN_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage14_shift_chain.json")
RESULTS_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage15_search_results.json")

PADDING_CYCLES = 113   # 125 total enable-high cycles - 12 candidate cycles = 113 padding
EXTRA_CYCLES_AFTER_ENABLE_DROP = 30


def bits_msb_first(value, width):
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def decode_output_message(byte_list):
    chars = []
    for v in byte_list:
        if v == 0:
            chars.append("<NUL>")
        elif 32 <= v <= 126:
            chars.append(chr(v))
        else:
            chars.append(f"\\x{v:02x}")
    return "".join(chars)


def try_candidate(netlist, width, bit_sequence):
    sim = Simulator(netlist)
    sim.step(rst_n=False, clk=False, enable=False, I=False)
    sim.step(rst_n=True, clk=False)

    output_bytes = []
    success_cycle = None
    cycle = 0

    # Padding cycles -- fill the pipeline with enable held high, arbitrary I.
    for _ in range(PADDING_CYCLES):
        cycle += 1
        sim.step(enable=True, I=False, clk=True)
        if sim.read("success") and success_cycle is None:
            success_cycle = cycle
        sim.step(clk=False)

    # The actual candidate bits -- these are what end up in the register.
    for bit in bit_sequence:
        cycle += 1
        sim.step(enable=True, I=bool(bit), clk=True)
        if sim.read("success") and success_cycle is None:
            success_cycle = cycle
        sim.step(clk=False)

    # Observe.
    for _ in range(EXTRA_CYCLES_AFTER_ENABLE_DROP):
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

    return (success_cycle is not None), success_cycle, output_bytes


def main():
    print("=== Stage 15 (v2): Brute-Force Search (duration-corrected) ===\n")

    with open(SHIFT_CHAIN_FILE) as f:
        chain = json.load(f)
    width = len(chain)
    total_cycles_per_trial = PADDING_CYCLES + width + EXTRA_CYCLES_AFTER_ENABLE_DROP
    print(f"Register width: {width} bits ({2**width} combinations, single ordering --")
    print(f"see module docstring for why one ordering already gives full coverage)")
    print(f"Cycles per trial: {PADDING_CYCLES} padding + {width} candidate + "
          f"{EXTRA_CYCLES_AFTER_ENABLE_DROP} observe = {total_cycles_per_trial}\n")

    netlist = load_netlist(NETLIST_FILE)

    hits = []
    t0 = time.time()
    total_trials = 2 ** width

    for value in range(total_trials):
        bit_sequence = bits_msb_first(value, width)
        triggered, success_cycle, output_bytes = try_candidate(netlist, width, bit_sequence)

        if triggered:
            message = decode_output_message(output_bytes)
            print(f"\n*** SUCCESS TRIGGERED ***")
            print(f"  Value: {value} (binary: {value:0{width}b})")
            print(f"  Bit sequence fed: {bit_sequence}")
            print(f"  Success first observed at cycle {success_cycle}")
            print(f"  Output message: {message}")
            hits.append({
                "value": value, "bit_sequence": bit_sequence,
                "success_cycle": success_cycle, "output_message": message,
            })

        if (value + 1) % 500 == 0 or (value + 1) == total_trials:
            elapsed = time.time() - t0
            rate = (value + 1) / elapsed if elapsed > 0 else 0
            remaining = (total_trials - (value + 1)) / rate if rate > 0 else 0
            print(f"  ...{value+1}/{total_trials} trials, {elapsed:.1f}s elapsed, "
                  f"~{remaining:.0f}s remaining")

    print(f"\n=== Search complete: {total_trials} trials, {time.time()-t0:.1f}s total ===\n")

    if hits:
        print(f"Found {len(hits)} success-triggering input(s):")
        for h in hits:
            print(f"  value={h['value']} binary={h['value']:0{width}b} "
                  f"-> \"{h['output_message']}\"")
    else:
        print("Still no success-triggering input found. Worth checking:")
        print("  - Was 121 cycles really the FIRST phase's full duration, or did")
        print("    Stage 15b's detection possibly miss an earlier/different transition?")
        print("  - Try increasing PADDING_CYCLES further (e.g. +20-30 more) in case 121")
        print("    was specific to this particular VCD's timing, not a fixed requirement.")
        print("  - Revisit whether success's dependency chain could indirectly depend on")
        print("    net_0562 after all (worth re-tracing explicitly, just to be certain).")

    with open(RESULTS_FILE, "w") as f:
        json.dump({"width": width, "total_trials": total_trials, "hits": hits}, f, indent=2)
    print(f"\n✓ Full results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()