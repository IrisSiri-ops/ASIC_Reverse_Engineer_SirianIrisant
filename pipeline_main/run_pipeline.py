"""
run_pipeline.py -- Runs the full ASIC reverse-engineering pipeline, in order.
====================================================================================

Usage
-----
    python3 run_pipeline.py                  # full pipeline, skips the slow
                                                brute-force stage (stage15) by
                                                default, since it's a known
                                                dead end (~40 min, superseded
                                                by stage16's symbolic search)
    python3 run_pipeline.py --include-bruteforce
                                              # runs EVERYTHING, including
                                                stage15, for full reproduction
                                                of the narrative (slow)
    python3 run_pipeline.py --from stage9_final_netlist.py
                                              # resume from a specific stage
                                                (useful after editing one
                                                stage and not wanting to
                                                redo earlier, slower ones)
    python3 run_pipeline.py --only stage16_symbolic_search.py
                                              # run just one stage

Each stage is run as a subprocess (matching how they were built and
individually validated -- each has its own `if __name__ == "__main__"`
entry point and computes its own paths relative to its own file location,
so this works regardless of where run_pipeline.py itself is invoked from).

Stops immediately on the first failure by default, since every later
stage depends on earlier ones' output files.
"""

import argparse
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Ordered exactly as the pipeline must run -- each stage's output feeds
# the next. (script_filename, human_label, slow_and_skippable_by_default)
STAGES = [
    ("stage1_extract_instances.py",          "Stage 1: Extract gate instances", False),
    ("stage1b_extract_clkbuf_instances.py",  "Stage 1b: Extract clkbuf instances", False),
    ("stage1b_clkbuf_pins.py",               "Stage 1b: Clkbuf pin positions", False),
    ("stage1c_instance_footprints.py",       "Stage 1c: Instance footprints", False),
    ("stage2_extract_pins.py",               "Stage 2: Cell pin definitions", False),
    ("stage3_absolute_pin_positions.py",     "Stage 3: Absolute pin positions", False),
    ("stage4a_extract_metal_polygons.py",    "Stage 4a: Metal/li1/nwell polygons", False),
    ("stage4b_extract_contacts.py",          "Stage 4b: Contact geometry", False),
    ("stage5_connectivity_grouping.py",      "Stage 5: Connectivity grouping (nets)", False),
    ("stage6a_pin_to_net.py",                "Stage 6a: Pin-to-net assignment", False),
    ("stage6bc_emit_netlist.py",             "Stage 6b/6c: Net naming & netlist emission", False),
    ("stage7_extract_netlist_graph.py",      "Stage 7: Netlist graph + clock-tree BFS", False),
    ("stage7b_diagnose_unmatched_pins.py",   "Stage 7b: Unmatched-pin diagnostic", False),
    ("stage8_port_lookup.py",                "Stage 8: Top-level port lookup", False),
    ("stage9_final_netlist.py",              "Stage 9: Final netlist assembly (net_0562 fix applied)", False),
    ("stage10_cell_library.py",              "Stage 10: Cell-behavior library self-test", False),
    ("stage11_simulator.py",                 "Stage 11: Simulator engine self-test", False),
    ("stage12_cycle_driver.py",              "Stage 12: Cycle driver smoke test", False),
    ("stage13_vcd_crosscheck.py",            "Stage 13: VCD cross-validation", False),
    ("stage14_analyze_shift_register.py",    "Stage 14: Shift-register structure analysis", False),
    ("stage15_bruteforce_search.py",         "Stage 15: Brute-force search (SLOW, known dead end)", True),
    ("stage16_symbolic_search.py",           "Stage 16: Symbolic (Z3) search -- finds the answer", False),
    ("stage17_confirm_answer.py",            "Stage 17: Confirm and display the final answer", False),
]


def run_stage(script_name, label):
    script_path = os.path.join(SCRIPT_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"  SKIPPED (file not found): {script_path}")
        return False

    print(f"\n{'='*70}")
    print(f"{label}")
    print(f"{'='*70}")

    t0 = time.time()
    result = subprocess.run([sys.executable, script_path], cwd=SCRIPT_DIR)
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"\n*** FAILED (exit code {result.returncode}) after {elapsed:.1f}s: {label} ***")
        return False

    print(f"\n--- Completed in {elapsed:.1f}s: {label} ---")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run the full ASIC reverse-engineering pipeline.")
    parser.add_argument("--include-bruteforce", action="store_true",
                         help="Also run stage15 (slow, ~40min, known not to find the answer -- "
                              "included only for full narrative reproduction).")
    parser.add_argument("--from", dest="from_stage", default=None,
                         help="Resume from this script filename (e.g. stage9_final_netlist.py), "
                              "skipping everything before it.")
    parser.add_argument("--only", dest="only_stage", default=None,
                         help="Run only this single script filename.")
    args = parser.parse_args()

    stages_to_run = STAGES

    if args.only_stage:
        stages_to_run = [s for s in STAGES if s[0] == args.only_stage]
        if not stages_to_run:
            print(f"No stage matches '{args.only_stage}'. Available scripts:")
            for s in STAGES:
                print(f"  {s[0]}")
            sys.exit(1)
    elif args.from_stage:
        names = [s[0] for s in STAGES]
        if args.from_stage not in names:
            print(f"No stage matches '{args.from_stage}'. Available scripts:")
            for s in STAGES:
                print(f"  {s[0]}")
            sys.exit(1)
        start_idx = names.index(args.from_stage)
        stages_to_run = STAGES[start_idx:]

    if not args.include_bruteforce:
        skipped = [s for s in stages_to_run if s[2]]
        stages_to_run = [s for s in stages_to_run if not s[2]]
        for s in skipped:
            print(f"(Skipping by default: {s[1]} -- pass --include-bruteforce to run it)")

    print(f"\nRunning {len(stages_to_run)} stage(s)...\n")

    overall_t0 = time.time()
    for script_name, label, _ in stages_to_run:
        success = run_stage(script_name, label)
        if not success:
            print(f"\nPipeline stopped due to failure. {time.time()-overall_t0:.1f}s elapsed "
                  f"before failure.")
            sys.exit(1)

    print(f"\n{'='*70}")
    print(f"ALL STAGES COMPLETED SUCCESSFULLY -- {time.time()-overall_t0:.1f}s total")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()