"""
Stage 16: Symbolic (SAT/SMT) Search for the Success-Triggering Input
==========================================================================

Why this exists
------------------
find_stateful_registers.py showed 58 flip-flops (not just 12) depend on
I -- the design is a running computation over the full ~121+ cycle input
stream, not a fixed 12-bit register checked once. That search space
(2^121) is far too large to brute force. This uses Z3 instead: represent
every cycle's I bit as a FREE symbolic variable, symbolically unroll the
entire circuit (same gate logic as Stage 10, re-implemented with Z3's
boolean operators since Python's and/or/all() don't work on symbolic
expressions), and let the solver search intelligently for a satisfying
assignment where success becomes true -- rather than enumerate.

Design
------
- Combinational logic is a DAG (proven by Stage 11's convergence
  behavior) -- so each cycle's net values can be computed with ONE
  topological pass building Z3 expressions, no iteration needed.
- Flip-flop state carries across cycles as symbolic expressions (Q at
  cycle t+1 = D's expression at cycle t, since RESET_B/SET_B are held
  released throughout the loading phase after the initial concrete
  reset).
- I at every cycle (1..N) is a free Z3 Bool variable -- the solver
  decides all of them simultaneously, unlike brute force which had to
  guess a fixed-width window.
- After the N loading cycles, M more cycles run with I=False (concrete)
  to let the design's evaluation/output phase complete, matching the
  real VCD's observed pattern (message only appears after enable drops).
- Ask Z3 to satisfy: success == True at ANY of the checked cycles.

If SAT: extract the model, decode the winning I-bit sequence.
If UNSAT: means N cycles is not enough (or timing model is still wrong)
-- would need to try more cycles, which the script supports adjusting.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage10_cell_library import SEQ_CELLS  # plain data, safe to reuse directly

import z3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)
NETLIST_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage9_final_netlist.json")

N_LOAD_CYCLES = 121   # matches real VCD's confirmed first-phase duration
M_OBSERVE_CYCLES = 30  # extra cycles after loading, to observe success/output
SOLVER_TIMEOUT_MS = 30 * 60 * 1000  # 30 minutes; adjust if needed


def base_name(cell_type):
    prefix = "sky130_fd_sc_hd__"
    return cell_type[len(prefix):] if cell_type.startswith(prefix) else cell_type


# ---------------------------------------------------------------------------
# Symbolic cell library -- same specs as stage10_cell_library.py, but built
# with z3.And/Or/Not instead of Python's and/or/not/all/any (which don't
# work on symbolic expressions). Duplicated deliberately rather than
# refactoring shared code under time pressure -- stage10's specs are already
# VCD-validated, so copying the exact same group definitions is low-risk.
# ---------------------------------------------------------------------------

def z3_resolve(pin_name, active_low, inputs):
    val = inputs[pin_name]
    return z3.Not(val) if active_low else val


def z3_nway(pins, kind):
    is_and = kind.endswith("and")
    invert = kind.startswith("n")

    def fn(inputs):
        vals = [z3_resolve(p, al, inputs) for p, al in pins]
        result = z3.And(*vals) if is_and else z3.Or(*vals)
        return z3.Not(result) if invert else result
    return fn


def z3_sop(groups, invert=False):
    def fn(inputs):
        terms = [z3.And(*[z3_resolve(p, al, inputs) for p, al in group]) for group in groups]
        result = z3.Or(*terms)
        return z3.Not(result) if invert else result
    return fn


def z3_pos(groups, invert=False):
    def fn(inputs):
        terms = [z3.Or(*[z3_resolve(p, al, inputs) for p, al in group]) for group in groups]
        result = z3.And(*terms)
        return z3.Not(result) if invert else result
    return fn


def z3_xor(a, b, invert=False):
    def fn(inputs):
        result = z3.Xor(inputs[a], inputs[b])
        return z3.Not(result) if invert else result
    return fn


def z3_mux(a0, a1, sel):
    def fn(inputs):
        return z3.If(inputs[sel], inputs[a1], inputs[a0])
    return fn


def z3_buf(a):
    return lambda inputs: inputs[a]


def z3_inv(a):
    return lambda inputs: z3.Not(inputs[a])


Z3_COMB_CELLS = {}
Z3_COMB_CELLS["buf_2"] = {"output": "X", "fn": z3_buf("A")}
Z3_COMB_CELLS["inv_2"] = {"output": "Y", "fn": z3_inv("A")}
Z3_COMB_CELLS["clkbuf_4"] = {"output": "X", "fn": z3_buf("A")}
Z3_COMB_CELLS["clkbuf_8"] = {"output": "X", "fn": z3_buf("A")}
Z3_COMB_CELLS["clkbuf_16"] = {"output": "X", "fn": z3_buf("A")}

Z3_COMB_CELLS["and2_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False)], "and")}
Z3_COMB_CELLS["and2b_2"] = {"output": "X", "fn": z3_nway([("A_N", True), ("B", False)], "and")}
Z3_COMB_CELLS["and3_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False), ("C", False)], "and")}
Z3_COMB_CELLS["and3b_2"] = {"output": "X", "fn": z3_nway([("A_N", True), ("B", False), ("C", False)], "and")}
Z3_COMB_CELLS["and4_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False), ("C", False), ("D", False)], "and")}
Z3_COMB_CELLS["and4b_2"] = {"output": "X", "fn": z3_nway([("A_N", True), ("B", False), ("C", False), ("D", False)], "and")}
Z3_COMB_CELLS["and4bb_2"] = {"output": "X", "fn": z3_nway([("A_N", True), ("B_N", True), ("C", False), ("D", False)], "and")}

Z3_COMB_CELLS["nand2_2"] = {"output": "Y", "fn": z3_nway([("A", False), ("B", False)], "nand")}
Z3_COMB_CELLS["nand2b_2"] = {"output": "Y", "fn": z3_nway([("A_N", True), ("B", False)], "nand")}
Z3_COMB_CELLS["nand3_2"] = {"output": "Y", "fn": z3_nway([("A", False), ("B", False), ("C", False)], "nand")}
Z3_COMB_CELLS["nand3b_2"] = {"output": "Y", "fn": z3_nway([("A_N", True), ("B", False), ("C", False)], "nand")}
Z3_COMB_CELLS["nand4_2"] = {"output": "Y", "fn": z3_nway([("A", False), ("B", False), ("C", False), ("D", False)], "nand")}

Z3_COMB_CELLS["or2_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False)], "or")}
Z3_COMB_CELLS["or3_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False), ("C", False)], "or")}
Z3_COMB_CELLS["or3b_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False), ("C_N", True)], "or")}
Z3_COMB_CELLS["or4_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False), ("C", False), ("D", False)], "or")}
Z3_COMB_CELLS["or4b_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False), ("C", False), ("D_N", True)], "or")}
Z3_COMB_CELLS["or4bb_2"] = {"output": "X", "fn": z3_nway([("A", False), ("B", False), ("C_N", True), ("D_N", True)], "or")}

Z3_COMB_CELLS["nor2_2"] = {"output": "Y", "fn": z3_nway([("A", False), ("B", False)], "nor")}
Z3_COMB_CELLS["nor3_2"] = {"output": "Y", "fn": z3_nway([("A", False), ("B", False), ("C", False)], "nor")}
Z3_COMB_CELLS["nor3b_2"] = {"output": "Y", "fn": z3_nway([("A", False), ("B", False), ("C_N", True)], "nor")}
Z3_COMB_CELLS["nor4_2"] = {"output": "Y", "fn": z3_nway([("A", False), ("B", False), ("C", False), ("D", False)], "nor")}
Z3_COMB_CELLS["nor4b_2"] = {"output": "Y", "fn": z3_nway([("A", False), ("B", False), ("C", False), ("D_N", True)], "nor")}

Z3_COMB_CELLS["a21o_2"] = {"output": "X", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False)]], False)}
Z3_COMB_CELLS["a21oi_2"] = {"output": "Y", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False)]], True)}
Z3_COMB_CELLS["a21bo_2"] = {"output": "X", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1_N", True)]], False)}
Z3_COMB_CELLS["a21boi_2"] = {"output": "Y", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1_N", True)]], True)}
Z3_COMB_CELLS["a211o_2"] = {"output": "X", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)]], False)}
Z3_COMB_CELLS["a211oi_2"] = {"output": "Y", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)]], True)}
Z3_COMB_CELLS["a2111oi_2"] = {"output": "Y", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)], [("D1", False)]], True)}
Z3_COMB_CELLS["a221o_2"] = {"output": "X", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)], [("C1", False)]], False)}
Z3_COMB_CELLS["a221oi_2"] = {"output": "Y", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)], [("C1", False)]], True)}
Z3_COMB_CELLS["a22o_2"] = {"output": "X", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)]], False)}
Z3_COMB_CELLS["a22oi_2"] = {"output": "Y", "fn": z3_sop([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)]], True)}
Z3_COMB_CELLS["a311o_2"] = {"output": "X", "fn": z3_sop([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)], [("C1", False)]], False)}
Z3_COMB_CELLS["a31o_2"] = {"output": "X", "fn": z3_sop([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)]], False)}
Z3_COMB_CELLS["a31oi_2"] = {"output": "Y", "fn": z3_sop([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)]], True)}
Z3_COMB_CELLS["a32o_2"] = {"output": "X", "fn": z3_sop([[("A1", False), ("A2", False), ("A3", False)], [("B1", False), ("B2", False)]], False)}
Z3_COMB_CELLS["a41oi_2"] = {"output": "Y", "fn": z3_sop([[("A1", False), ("A2", False), ("A3", False), ("A4", False)], [("B1", False)]], True)}

Z3_COMB_CELLS["o21a_2"] = {"output": "X", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1", False)]], False)}
Z3_COMB_CELLS["o21ai_2"] = {"output": "Y", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1", False)]], True)}
Z3_COMB_CELLS["o21ba_2"] = {"output": "X", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1_N", True)]], False)}
Z3_COMB_CELLS["o21bai_2"] = {"output": "Y", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1_N", True)]], True)}
Z3_COMB_CELLS["o211a_2"] = {"output": "X", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)]], False)}
Z3_COMB_CELLS["o211ai_2"] = {"output": "Y", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1", False)], [("C1", False)]], True)}
Z3_COMB_CELLS["o221a_2"] = {"output": "X", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)], [("C1", False)]], False)}
Z3_COMB_CELLS["o22a_2"] = {"output": "X", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)]], False)}
Z3_COMB_CELLS["o22ai_2"] = {"output": "Y", "fn": z3_pos([[("A1", False), ("A2", False)], [("B1", False), ("B2", False)]], True)}
Z3_COMB_CELLS["o2bb2a_2"] = {"output": "X", "fn": z3_pos([[("A1_N", True), ("A2_N", True)], [("B1", False), ("B2", False)]], False)}
Z3_COMB_CELLS["o311a_2"] = {"output": "X", "fn": z3_pos([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)], [("C1", False)]], False)}
Z3_COMB_CELLS["o31a_2"] = {"output": "X", "fn": z3_pos([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)]], False)}
Z3_COMB_CELLS["o31ai_2"] = {"output": "Y", "fn": z3_pos([[("A1", False), ("A2", False), ("A3", False)], [("B1", False)]], True)}
Z3_COMB_CELLS["o32a_2"] = {"output": "X", "fn": z3_pos([[("A1", False), ("A2", False), ("A3", False)], [("B1", False), ("B2", False)]], False)}
Z3_COMB_CELLS["o32ai_2"] = {"output": "Y", "fn": z3_pos([[("A1", False), ("A2", False), ("A3", False)], [("B1", False), ("B2", False)]], True)}

Z3_COMB_CELLS["xor2_2"] = {"output": "X", "fn": z3_xor("A", "B", False)}
Z3_COMB_CELLS["xnor2_2"] = {"output": "Y", "fn": z3_xor("A", "B", True)}
Z3_COMB_CELLS["mux2_1"] = {"output": "X", "fn": z3_mux("A0", "A1", "S")}

Z3_TIE_CELLS = {"conb_1": {"HI": True, "LO": False}}
Z3_NON_FUNCTIONAL = {"diode_2"}


class SymbolicCircuit:
    def __init__(self, netlist):
        self.ports = netlist["ports"]
        self.instances = netlist["instances"]

        self.comb_order = []   # topologically sorted list of (output_net, input_map, fn)
        self.seq_list = []     # list of dicts: d_net, q_net
        self._build()

    def _build(self):
        comb_by_output = {}
        for inst in self.instances:
            base = base_name(inst["cell_type"])
            pins = inst["pins"]
            if base in Z3_COMB_CELLS:
                spec = Z3_COMB_CELLS[base]
                output_net = pins[spec["output"]]
                input_map = {p: n for p, n in pins.items() if p not in (spec["output"], "VPWR", "VGND")}
                comb_by_output[output_net] = (input_map, spec["fn"])
            elif base in SEQ_CELLS:
                spec = SEQ_CELLS[base]
                self.seq_list.append({
                    "d_net": pins[spec["D"]], "q_net": pins[spec["Q"]],
                })

        visited, order = set(), []

        def visit(net):
            if net in visited or net not in comb_by_output:
                return
            visited.add(net)
            input_map, _ = comb_by_output[net]
            for in_net in input_map.values():
                visit(in_net)
            order.append(net)

        for net in list(comb_by_output.keys()):
            visit(net)

        for net in order:
            input_map, fn = comb_by_output[net]
            self.comb_order.append((net, input_map, fn))

    def eval_cycle(self, ff_state, primary_inputs, cycle_index):
        """ff_state: dict q_net -> z3 expr (current). primary_inputs: dict
        net_name -> z3 expr for this cycle's clk/rst_n/enable/I nets.
        cycle_index: used to generate unique fresh-variable names for any
        undriven net encountered (e.g. net_0562 -- see STATUS_net_0562.md;
        provably doesn't reach success, so an unconstrained free variable
        here has no effect on solvability, but keeps the evaluator from
        crashing the way a raw dict lookup would)."""
        net_values = dict(ff_state)
        net_values.update(primary_inputs)
        net_values["VPWR"] = z3.BoolVal(True)
        net_values["VGND"] = z3.BoolVal(False)

        for inst in self.instances:
            base = base_name(inst["cell_type"])
            if base in Z3_TIE_CELLS:
                for pin_name, val in Z3_TIE_CELLS[base].items():
                    net_values[inst["pins"][pin_name]] = z3.BoolVal(val)

        def get_or_create(net_name):
            if net_name not in net_values:
                # Undriven net (known case: net_0562) -- unconstrained free
                # variable, unique per cycle to avoid accidental cross-cycle
                # correlation for what is genuinely disconnected logic.
                net_values[net_name] = z3.Bool(f"_undriven_{net_name}_{cycle_index}")
            return net_values[net_name]

        for output_net, input_map, fn in self.comb_order:
            inputs = {p: get_or_create(n) for p, n in input_map.items()}
            net_values[output_net] = fn(inputs)

        new_ff_state = {}
        for seq in self.seq_list:
            new_ff_state[seq["q_net"]] = net_values.get(seq["d_net"], z3.BoolVal(False))

        return net_values, new_ff_state


def main():
    print("=== Stage 16: Symbolic (Z3) Search ===\n")

    with open(NETLIST_FILE) as f:
        netlist = json.load(f)

    print("Building symbolic circuit (topological sort)...")
    circuit = SymbolicCircuit(netlist)
    print(f"Combinational gates: {len(circuit.comb_order)}")
    print(f"Flip-flops: {len(circuit.seq_list)}\n")

    i_net = netlist["ports"]["I"]["net_name"]
    clk_net = netlist["ports"]["clk"]["net_name"]
    rst_n_net = netlist["ports"]["rst_n"]["net_name"]
    enable_net = netlist["ports"]["enable"]["net_name"]
    success_net = netlist["ports"]["success"]["net_name"]

    ff_state = {seq["q_net"]: z3.BoolVal(False) for seq in circuit.seq_list}

    i_vars = []
    success_terms = []

    t0 = time.time()
    print(f"Unrolling {N_LOAD_CYCLES} load cycles (I is FREE per cycle) + "
          f"{M_OBSERVE_CYCLES} observe cycles...")

    for cycle in range(N_LOAD_CYCLES):
        i_var = z3.Bool(f"I_{cycle}")
        i_vars.append(i_var)
        primary_inputs = {
            i_net: i_var,
            clk_net: z3.BoolVal(True),      # placeholder -- clk edges are abstracted away;
                                              # this cycle model updates all flops once per
                                              # call, so clk's own value doesn't drive logic,
                                              # it just needs to be present for clkbuf's
                                              # combinational evaluation to resolve.
            rst_n_net: z3.BoolVal(True),     # reset released throughout the load phase
            enable_net: z3.BoolVal(True),    # enable held high while loading, matching
                                              # the real VCD's confirmed protocol
        }
        net_values, ff_state = circuit.eval_cycle(ff_state, primary_inputs, cycle)
        success_terms.append(net_values.get(success_net, z3.BoolVal(False)))
        if (cycle + 1) % 20 == 0:
            print(f"  ...{cycle+1}/{N_LOAD_CYCLES} load cycles unrolled ({time.time()-t0:.1f}s)")

    for cycle in range(M_OBSERVE_CYCLES):
        primary_inputs = {
            i_net: z3.BoolVal(False),
            clk_net: z3.BoolVal(True),
            rst_n_net: z3.BoolVal(True),
            enable_net: z3.BoolVal(False),   # enable dropped -- observe/evaluate phase
        }
        net_values, ff_state = circuit.eval_cycle(ff_state, primary_inputs, N_LOAD_CYCLES + cycle)
        success_terms.append(net_values.get(success_net, z3.BoolVal(False)))

    print(f"\nUnrolling complete ({time.time()-t0:.1f}s). Building solver query...")

    solver = z3.Solver()
    solver.set("timeout", SOLVER_TIMEOUT_MS)
    solver.add(z3.Or(*success_terms))

    print("Solving (this may take a while)...")
    t1 = time.time()
    result = solver.check()
    print(f"Solver finished in {time.time()-t1:.1f}s: {result}\n")

    if result == z3.sat:
        model = solver.model()
        bits = [1 if z3.is_true(model.eval(v, model_completion=True)) else 0 for v in i_vars]
        print("*** SATISFIABLE -- found an input sequence! ***")
        print(f"Bit sequence ({len(bits)} bits): {bits}")
        with open(os.path.join(PUZZLE_DIR, "output_main", "stage16_sat_result.json"), "w") as f:
            json.dump({"result": "sat", "bits": bits}, f, indent=2)
        print("\n✓ Saved to output_main/stage16_sat_result.json")
        print("\nNext step: feed this exact bit sequence through the Stage 12 driver")
        print("(concrete, not symbolic) to confirm and read the full output message.")
    elif result == z3.unsat:
        print("UNSAT -- no satisfying assignment exists within "
              f"{N_LOAD_CYCLES}+{M_OBSERVE_CYCLES} cycles.")
        print("This means N_LOAD_CYCLES needs to be larger, or something else in the")
        print("timing/reset model is still off. Try increasing N_LOAD_CYCLES and rerun.")
    else:
        print(f"Solver returned '{result}' -- likely timed out. Consider raising")
        print("SOLVER_TIMEOUT_MS, or reducing N_LOAD_CYCLES/M_OBSERVE_CYCLES if the")
        print("formula is too large to solve in reasonable time.")


if __name__ == "__main__":
    main()