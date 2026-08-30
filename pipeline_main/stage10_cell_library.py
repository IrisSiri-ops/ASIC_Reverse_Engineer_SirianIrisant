"""
====================================================================
PHASE 3: CELL-BEHAVIOR LIBRARY
====================================================================
Stage 10: Cell Behavior Definitions
--------------------------------------

Purpose
-------
Defines the boolean (combinational) or sequential-update function of every
cell type actually present in the recovered design -- the 64 gate types
from Stage 1's breakdown plus the 3 clkbuf sizes from Stage 1b. This is
the core of the "GDS in, answer out" claim: nothing here comes from Sky130's
vendor Verilog models. Every function is the standard textbook boolean
identity implied by the Sky130 *naming convention* itself (public, general
knowledge of how the PDK names cells -- not a copy of proprietary behavioral
source), cross-checked pin-name-for-pin-name against the actual instance
declarations in puzzle_final.v (Stage 9's output), not guessed.

Design
------
Rather than 67 hand-written near-duplicate functions (error-prone -- a typo
in one AOI variant is easy to miss), this file uses two small generic
builders that mirror Sky130's own naming logic:

  - `sop_gate(groups, invert)`  : AND each group of pins, then OR the
    groups together, then optionally invert. This is the "a2Xo/a2Xoi"
    (AND-OR / AND-OR-INVERT) family.
  - `pos_gate(groups, invert)`  : OR each group of pins, then AND the
    groups together, then optionally invert. This is the "o2Xa/o2Xai"
    (OR-AND / OR-AND-INVERT) family.
  - `nway_gate(pins, kind)`     : plain N-input AND/OR/NAND/NOR, with
    per-pin polarity (for the "b"-suffixed cells whose pin is inverted
    at the input, e.g. and2b_2's A_N).

Each pin spec is (pin_name, active_low: bool). active_low=True means the
signal on that pin is inverted before being combined.

Confidence note
----------------
Every gate below follows directly from Sky130's documented naming
convention with one exception: `o2bb2a_2` is a rarer cell (only 1 instance
in this design) whose exact "bb" convention I'm less certain of by pattern-
matching alone. It's flagged explicitly below and should be the first
thing double-checked if Phase 6 (VCD cross-check) reveals a mismatch.
"""

import json
import os

# ---------------------------------------------------------------------------
# Generic builders
# ---------------------------------------------------------------------------

def _resolve(pin_name, active_low, inputs):
    val = inputs[pin_name]
    return (not val) if active_low else val


def nway_gate(pins, kind):
    """
    pins: list of (pin_name, active_low)
    kind: 'and', 'or', 'nand', 'nor'
    """
    invert = kind.startswith("n")
    is_and = kind.endswith("and")

    def fn(inputs):
        vals = [_resolve(p, al, inputs) for p, al in pins]
        result = all(vals) if is_and else any(vals)
        return (not result) if invert else result
    return fn


def sop_gate(groups, invert=False):
    """AND-OR family: OR of (AND of each group), optional final invert."""
    def fn(inputs):
        result = any(all(_resolve(p, al, inputs) for p, al in group) for group in groups)
        return (not result) if invert else result
    return fn


def pos_gate(groups, invert=False):
    """OR-AND family: AND of (OR of each group), optional final invert."""
    def fn(inputs):
        result = all(any(_resolve(p, al, inputs) for p, al in group) for group in groups)
        return (not result) if invert else result
    return fn


def xor_gate(a, b, invert=False):
    def fn(inputs):
        result = inputs[a] != inputs[b]
        return (not result) if invert else result
    return fn


def mux2_gate(a0, a1, sel):
    def fn(inputs):
        return inputs[a1] if inputs[sel] else inputs[a0]
    return fn


def buf_gate(a):
    def fn(inputs):
        return inputs[a]
    return fn


def inv_gate(a):
    def fn(inputs):
        return not inputs[a]
    return fn


# ---------------------------------------------------------------------------
# Combinational cell table: cell_suffix -> {"output": pin_name, "fn": callable}
# Pin names verified directly against puzzle_final.v instance declarations.
# ---------------------------------------------------------------------------

COMB_CELLS = {}

# --- simple buffer / inverter / clock buffers (all pure passthrough family) ---
COMB_CELLS["buf_2"]      = {"output": "X", "fn": buf_gate("A")}
COMB_CELLS["inv_2"]      = {"output": "Y", "fn": inv_gate("A")}
COMB_CELLS["clkbuf_4"]   = {"output": "X", "fn": buf_gate("A")}
COMB_CELLS["clkbuf_8"]   = {"output": "X", "fn": buf_gate("A")}
COMB_CELLS["clkbuf_16"]  = {"output": "X", "fn": buf_gate("A")}

# --- plain N-input AND/OR/NAND/NOR family ---
COMB_CELLS["and2_2"]   = {"output": "X", "fn": nway_gate([("A", False), ("B", False)], "and")}
COMB_CELLS["and2b_2"]  = {"output": "X", "fn": nway_gate([("A_N", True), ("B", False)], "and")}
COMB_CELLS["and3_2"]   = {"output": "X", "fn": nway_gate([("A", False), ("B", False), ("C", False)], "and")}
COMB_CELLS["and3b_2"]  = {"output": "X", "fn": nway_gate([("A_N", True), ("B", False), ("C", False)], "and")}
COMB_CELLS["and4_2"]   = {"output": "X", "fn": nway_gate([("A", False), ("B", False), ("C", False), ("D", False)], "and")}
COMB_CELLS["and4b_2"]  = {"output": "X", "fn": nway_gate([("A_N", True), ("B", False), ("C", False), ("D", False)], "and")}
COMB_CELLS["and4bb_2"] = {"output": "X", "fn": nway_gate([("A_N", True), ("B_N", True), ("C", False), ("D", False)], "and")}

COMB_CELLS["nand2_2"]  = {"output": "Y", "fn": nway_gate([("A", False), ("B", False)], "nand")}
COMB_CELLS["nand2b_2"] = {"output": "Y", "fn": nway_gate([("A_N", True), ("B", False)], "nand")}
COMB_CELLS["nand3_2"]  = {"output": "Y", "fn": nway_gate([("A", False), ("B", False), ("C", False)], "nand")}
COMB_CELLS["nand3b_2"] = {"output": "Y", "fn": nway_gate([("A_N", True), ("B", False), ("C", False)], "nand")}
COMB_CELLS["nand4_2"]  = {"output": "Y", "fn": nway_gate([("A", False), ("B", False), ("C", False), ("D", False)], "nand")}

COMB_CELLS["or2_2"]   = {"output": "X", "fn": nway_gate([("A", False), ("B", False)], "or")}
COMB_CELLS["or3_2"]   = {"output": "X", "fn": nway_gate([("A", False), ("B", False), ("C", False)], "or")}
COMB_CELLS["or3b_2"]  = {"output": "X", "fn": nway_gate([("A", False), ("B", False), ("C_N", True)], "or")}
COMB_CELLS["or4_2"]   = {"output": "X", "fn": nway_gate([("A", False), ("B", False), ("C", False), ("D", False)], "or")}
COMB_CELLS["or4b_2"]  = {"output": "X", "fn": nway_gate([("A", False), ("B", False), ("C", False), ("D_N", True)], "or")}
COMB_CELLS["or4bb_2"] = {"output": "X", "fn": nway_gate([("A", False), ("B", False), ("C_N", True), ("D_N", True)], "or")}

COMB_CELLS["nor2_2"]  = {"output": "Y", "fn": nway_gate([("A", False), ("B", False)], "nor")}
COMB_CELLS["nor3_2"]  = {"output": "Y", "fn": nway_gate([("A", False), ("B", False), ("C", False)], "nor")}
COMB_CELLS["nor3b_2"] = {"output": "Y", "fn": nway_gate([("A", False), ("B", False), ("C_N", True)], "nor")}
COMB_CELLS["nor4_2"]  = {"output": "Y", "fn": nway_gate([("A", False), ("B", False), ("C", False), ("D", False)], "nor")}
COMB_CELLS["nor4b_2"] = {"output": "Y", "fn": nway_gate([("A", False), ("B", False), ("C", False), ("D_N", True)], "nor")}

# --- AND-OR / AND-OR-INVERT family (sop_gate) ---
COMB_CELLS["a21o_2"]     = {"output": "X", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False)]], invert=False)}
COMB_CELLS["a21oi_2"]    = {"output": "Y", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False)]], invert=True)}
COMB_CELLS["a21bo_2"]    = {"output": "X", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1_N", True)]], invert=False)}
COMB_CELLS["a21boi_2"]   = {"output": "Y", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1_N", True)]], invert=True)}
COMB_CELLS["a211o_2"]    = {"output": "X", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)]], invert=False)}
COMB_CELLS["a211oi_2"]   = {"output": "Y", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)]], invert=True)}
COMB_CELLS["a2111oi_2"]  = {"output": "Y", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)], [("D1", False)]], invert=True)}
COMB_CELLS["a221o_2"]    = {"output": "X", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)], [("C1", False)]], invert=False)}
COMB_CELLS["a221oi_2"]   = {"output": "Y", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)], [("C1", False)]], invert=True)}
COMB_CELLS["a22o_2"]     = {"output": "X", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)]], invert=False)}
COMB_CELLS["a22oi_2"]    = {"output": "Y", "fn": sop_gate([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)]], invert=True)}
COMB_CELLS["a311o_2"]    = {"output": "X", "fn": sop_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)], [("C1", False)]], invert=False)}
COMB_CELLS["a31o_2"]     = {"output": "X", "fn": sop_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)]], invert=False)}
COMB_CELLS["a31oi_2"]    = {"output": "Y", "fn": sop_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)]], invert=True)}
COMB_CELLS["a32o_2"]     = {"output": "X", "fn": sop_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False), ("B2", False)]], invert=False)}
COMB_CELLS["a41oi_2"]    = {"output": "Y", "fn": sop_gate([[("A1", False), ("A2", False), ("A3", False), ("A4", False)], [("B1", False)]], invert=True)}

# --- OR-AND / OR-AND-INVERT family (pos_gate) ---
COMB_CELLS["o21a_2"]    = {"output": "X", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1", False)]], invert=False)}
COMB_CELLS["o21ai_2"]   = {"output": "Y", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1", False)]], invert=True)}
COMB_CELLS["o21ba_2"]   = {"output": "X", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1_N", True)]], invert=False)}
COMB_CELLS["o21bai_2"]  = {"output": "Y", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1_N", True)]], invert=True)}
COMB_CELLS["o211a_2"]   = {"output": "X", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)]], invert=False)}
COMB_CELLS["o211ai_2"]  = {"output": "Y", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)]], invert=True)}
COMB_CELLS["o221a_2"]   = {"output": "X", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)], [("C1", False)]], invert=False)}
COMB_CELLS["o22a_2"]    = {"output": "X", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)]], invert=False)}
COMB_CELLS["o22ai_2"]   = {"output": "Y", "fn": pos_gate([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)]], invert=True)}
# LOWER CONFIDENCE -- see module docstring. Only 1 instance in this design (o2bb2a_2__465).
COMB_CELLS["o2bb2a_2"]  = {"output": "X", "fn": pos_gate([[("A1_N", True), ("A2_N", True)], [("B1", False), ("B2", False)]], invert=False)}
COMB_CELLS["o311a_2"]   = {"output": "X", "fn": pos_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)], [("C1", False)]], invert=False)}
COMB_CELLS["o31a_2"]    = {"output": "X", "fn": pos_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)]], invert=False)}
COMB_CELLS["o31ai_2"]   = {"output": "Y", "fn": pos_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)]], invert=True)}
COMB_CELLS["o32a_2"]    = {"output": "X", "fn": pos_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False), ("B2", False)]], invert=False)}
COMB_CELLS["o32ai_2"]   = {"output": "Y", "fn": pos_gate([[("A1", False), ("A2", False), ("A3", False)], [("B1", False), ("B2", False)]], invert=True)}

# --- XOR / XNOR ---
COMB_CELLS["xor2_2"]  = {"output": "X", "fn": xor_gate("A", "B", invert=False)}
COMB_CELLS["xnor2_2"] = {"output": "Y", "fn": xor_gate("A", "B", invert=True)}

# --- MUX ---
COMB_CELLS["mux2_1"] = {"output": "X", "fn": mux2_gate("A0", "A1", "S")}


# ---------------------------------------------------------------------------
# Tie cells (constant drivers) -- no inputs, fixed outputs
# ---------------------------------------------------------------------------
TIE_CELLS = {
    "conb_1": {"HI": True, "LO": False},
}

# ---------------------------------------------------------------------------
# Non-functional cells -- present in the layout but carry no logical
# signal function (antenna diodes protect gate oxide during fab; they
# have no effect on simulated behavior).
# ---------------------------------------------------------------------------
NON_FUNCTIONAL_CELLS = {"diode_2"}

# ---------------------------------------------------------------------------
# Sequential cells: (D pin, Q pin, CLK pin, control pin, control type)
# control type: "reset" (active-low async reset to 0), "set" (active-low
# async set to 1), or None (plain DFF, no reset/set pin).
# Update rule (applied by the Phase 4/5 evaluator, not here):
#   - if control asserted (control pin == 0): Q = 0 (reset) or Q = 1 (set),
#     asynchronously -- independent of CLK.
#   - else, on a rising edge of CLK: Q <- D.
#   - else (no edge, no control asserted): Q holds.
# ---------------------------------------------------------------------------
SEQ_CELLS = {
    "dfrtp_2": {"D": "D", "Q": "Q", "CLK": "CLK", "ctrl_pin": "RESET_B", "ctrl_type": "reset"},
    "dfstp_2": {"D": "D", "Q": "Q", "CLK": "CLK", "ctrl_pin": "SET_B",   "ctrl_type": "set"},
    "dfxtp_2": {"D": "D", "Q": "Q", "CLK": "CLK", "ctrl_pin": None,     "ctrl_type": None},
}


# ---------------------------------------------------------------------------
# Self-test: coverage check against the real recovered netlist, plus a
# handful of truth-table sanity spot-checks on representative gates.
# ---------------------------------------------------------------------------

def _base_name(cell_type):
    prefix = "sky130_fd_sc_hd__"
    return cell_type[len(prefix):] if cell_type.startswith(prefix) else cell_type


def coverage_check():
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)
    NETLIST_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage9_final_netlist.json")

    if not os.path.exists(NETLIST_FILE):
        print("(stage9_final_netlist.json not found -- skipping coverage check)")
        return

    with open(NETLIST_FILE) as f:
        netlist = json.load(f)

    all_defined = set(COMB_CELLS) | set(TIE_CELLS) | NON_FUNCTIONAL_CELLS | set(SEQ_CELLS)
    used_types = {_base_name(inst["cell_type"]) for inst in netlist["instances"]}

    missing = used_types - all_defined
    unused = all_defined - used_types

    print(f"Cell types used in design: {len(used_types)}")
    print(f"Cell types defined in this library: {len(all_defined)}")
    if missing:
        print(f"❌ MISSING definitions for types used in the design: {sorted(missing)}")
    else:
        print("✓ Every cell type used in the recovered design has a definition here.")
    if unused:
        print(f"(Defined but not used in this design: {sorted(unused)})")


def sanity_spot_checks():
    print("\n=== Truth-table spot checks ===")
    checks = [
        ("and2_2", {"A": True, "B": True}, True),
        ("and2_2", {"A": True, "B": False}, False),
        ("nand2_2", {"A": True, "B": True}, False),
        ("or2_2", {"A": False, "B": False}, False),
        ("nor2_2", {"A": False, "B": False}, True),
        ("xor2_2", {"A": True, "B": False}, True),
        ("xnor2_2", {"A": True, "B": True}, True),
        ("inv_2", {"A": True}, False),
        ("buf_2", {"A": True}, True),
        ("and2b_2", {"A_N": False, "B": True}, True),   # ~A_N & B = ~0 & 1 = 1
        ("and2b_2", {"A_N": True, "B": True}, False),   # ~1 & 1 = 0
        ("a21o_2", {"A1": True, "A2": True, "B1": False}, True),   # (1&1)|0 = 1
        ("a21o_2", {"A1": True, "A2": False, "B1": False}, False), # (1&0)|0 = 0
        ("a21oi_2", {"A1": True, "A2": True, "B1": False}, False),
        ("o21a_2", {"A1": False, "A2": False, "B1": True}, False),  # (0|0)&1 = 0
        ("o21a_2", {"A1": True, "A2": False, "B1": True}, True),    # (1|0)&1 = 1
        ("o21ai_2", {"A1": True, "A2": False, "B1": True}, False),
        ("mux2_1", {"A0": False, "A1": True, "S": True}, True),
        ("mux2_1", {"A0": False, "A1": True, "S": False}, False),
    ]
    failures = 0
    for cell, inputs, expected in checks:
        got = COMB_CELLS[cell]["fn"](inputs)
        status = "✓" if got == expected else "❌"
        if got != expected:
            failures += 1
        print(f"  {status} {cell}({inputs}) = {got}  (expected {expected})")
    print(f"\n{len(checks) - failures}/{len(checks)} spot checks passed.")
    if failures:
        print("⚠️  Fix the failing gate definition(s) above before proceeding to Phase 4.")


def main():
    print("=== PUZZLE STAGE 10 (Phase 3: Cell-Behavior Library) — Self-Test ===\n")
    coverage_check()
    sanity_spot_checks()


if __name__ == "__main__":
    main()