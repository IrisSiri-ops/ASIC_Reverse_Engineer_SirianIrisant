"""
====================================================================
PHASE 4: NETLIST EVALUATOR
====================================================================
Stage 11: Cycle-Based Netlist Simulator Engine
--------------------------------------------------

Purpose
-------
Turns the recovered netlist (stage9_final_netlist.json) plus the cell
behavior library (stage10_cell_library.py) into an actual simulator:
given primary input values (clk, rst_n, enable, I) at each step, computes
every net's value in the design, including success and O[0:7].

Design
------
Two-phase evaluation per step, matching standard synchronous digital
circuit semantics:

  1. COMBINATIONAL SETTLE: propagate values through all combinational
     gates to a fixed point (iterate until nothing changes). The
     combinational logic between register boundaries is a DAG (no
     combinational loops), so this always terminates -- if it doesn't
     within MAX_SETTLE_ITERS, that's flagged loudly as a real problem
     worth investigating, not silently ignored.

  2. FLIP-FLOP UPDATE: for each sequential cell (dfrtp_2/dfstp_2/dfxtp_2),
     check its async control pin (RESET_B/SET_B) first -- if asserted,
     force Q immediately, independent of clock. Otherwise, if CLK just
     rose (0->1 since the last step), latch D into Q. Otherwise Q holds.

     This is where reset sequencing -- the thing that blocked the
     iverilog route entirely -- becomes fully explicit and under direct
     control: asserting rst_n and settling BEFORE ever toggling clk
     forces every resettable flop to a known 0 state deterministically,
     with no UDP delta-cycle timing to fight.

After a flip-flop update, the combinational network is re-settled once
more, since changed Q values can ripple into other combinational logic
(including nets that feed back into other D inputs and into O[0:7]/success
directly).

Modeling note: dfxtp_2 instances (4 in this design, no reset pin) start
at False (0) by convention in this simulator, since Python has no native
"undefined" boolean. This is a modeling choice worth remembering when
interpreting early-cycle behavior -- real silicon's power-on state for an
unreset register is technically undefined. Phase 6 (VCD cross-check)
should help clarify whether this assumption holds by comparing against a
real captured trace.
"""

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage10_cell_library import COMB_CELLS, TIE_CELLS, NON_FUNCTIONAL_CELLS, SEQ_CELLS

MAX_SETTLE_ITERS = 500


def _base_name(cell_type):
    prefix = "sky130_fd_sc_hd__"
    return cell_type[len(prefix):] if cell_type.startswith(prefix) else cell_type


class Simulator:
    def __init__(self, netlist):
        """
        netlist: the dict loaded from stage9_final_netlist.json
                 (keys: "ports", "nets", "instances")
        """
        self.ports = netlist["ports"]
        self.net_values = {}          # net_name -> bool
        self._comb_instances = []     # list of (output_net, input_map, fn)
        self._seq_instances = []      # list of dicts: d_net,q_net,clk_net,ctrl_net,ctrl_type,key
        self._prev_clk = {}           # seq instance key -> previous CLK value

        self._categorize(netlist["instances"])
        self._init_constants()

    def _categorize(self, instances):
        for inst in instances:
            base = _base_name(inst["cell_type"])
            pins = inst["pins"]
            key = f"{inst['cell_type']}__{inst['instance_id']}"

            if base in TIE_CELLS:
                for pin_name, value in TIE_CELLS[base].items():
                    net = pins[pin_name]
                    self.net_values[net] = value

            elif base in NON_FUNCTIONAL_CELLS:
                continue  # antenna diodes: no logical function

            elif base in SEQ_CELLS:
                spec = SEQ_CELLS[base]
                self._seq_instances.append({
                    "key": key,
                    "d_net": pins[spec["D"]],
                    "q_net": pins[spec["Q"]],
                    "clk_net": pins[spec["CLK"]],
                    "ctrl_net": pins[spec["ctrl_pin"]] if spec["ctrl_pin"] else None,
                    "ctrl_type": spec["ctrl_type"],
                })
                self._prev_clk[key] = False
                # Q starts at False (see module docstring modeling note).
                self.net_values.setdefault(pins[spec["Q"]], False)

            elif base in COMB_CELLS:
                spec = COMB_CELLS[base]
                output_pin = spec["output"]
                output_net = pins[output_pin]
                input_pin_names = [p for p in pins if p not in (output_pin, "VPWR", "VGND")]
                input_map = {p: pins[p] for p in input_pin_names}
                self._comb_instances.append((output_net, input_map, spec["fn"]))

            else:
                raise ValueError(f"Unknown cell type with no behavior definition: {inst['cell_type']}")

        # VPWR/VGND: tie high/low globally. Every instance's own VPWR/VGND
        # pin maps to the same net names (from Stage 9's naming), so these
        # two assignments cover the whole design.
        self.net_values["VPWR"] = True
        self.net_values["VGND"] = False

    def _init_constants(self):
        # Primary inputs start at 0 until the driver sets them explicitly.
        for port_name, info in self.ports.items():
            if info["direction"] == "input":
                self.net_values.setdefault(info["net_name"], False)

    def set_inputs(self, **kwargs):
        """
        Set primary input values by port name, e.g. set_inputs(clk=True, rst_n=False).
        Port names with special characters (e.g. 'O[0]') aren't valid kwargs,
        but those are outputs anyway and never set here.
        """
        for name, value in kwargs.items():
            if name not in self.ports or self.ports[name]["direction"] != "input":
                raise ValueError(f"'{name}' is not a primary input port")
            self.net_values[self.ports[name]["net_name"]] = value

    def settle_combinational(self):
        for iteration in range(MAX_SETTLE_ITERS):
            changed = False
            for output_net, input_map, fn in self._comb_instances:
                try:
                    inputs = {pin: self.net_values[net] for pin, net in input_map.items()}
                except KeyError:
                    continue  # not all inputs resolved yet this pass
                result = fn(inputs)
                if self.net_values.get(output_net) != result:
                    self.net_values[output_net] = result
                    changed = True
            if not changed:
                return iteration
        raise RuntimeError(
            f"Combinational settle did not converge within {MAX_SETTLE_ITERS} iterations -- "
            f"this suggests a real combinational loop, not expected for this design. "
            f"Investigate before trusting simulation results."
        )

    def update_flipflops(self):
        for seq in self._seq_instances:
            current_clk = self.net_values.get(seq["clk_net"], False)
            prev_clk = self._prev_clk[seq["key"]]

            async_asserted = (
                seq["ctrl_net"] is not None and
                self.net_values.get(seq["ctrl_net"], True) == False  # active-low
            )

            if async_asserted:
                new_q = (seq["ctrl_type"] == "set")
            elif current_clk and not prev_clk:  # rising edge
                new_q = self.net_values.get(seq["d_net"], False)
            else:
                new_q = self.net_values.get(seq["q_net"], False)

            self.net_values[seq["q_net"]] = new_q
            self._prev_clk[seq["key"]] = current_clk

    def step(self, **input_updates):
        """
        Apply primary input changes, settle combinational logic, update
        flip-flops (which may latch new values or apply async reset/set),
        then re-settle since Q changes can ripple into combinational logic
        (including directly into outputs).
        """
        if input_updates:
            self.set_inputs(**input_updates)
        self.settle_combinational()
        self.update_flipflops()
        self.settle_combinational()

    def read(self, port_name):
        info = self.ports[port_name]
        return self.net_values.get(info["net_name"])

    def read_outputs(self):
        return {
            name: self.net_values.get(info["net_name"])
            for name, info in self.ports.items()
            if info["direction"] == "output"
        }

    def unresolved_nets(self, all_net_names):
        """Diagnostic: which nets never got a value after settling. Should be empty
        in a healthy design; a non-empty result points at a real driver gap."""
        return [n for n in all_net_names if n not in self.net_values]


def load_netlist(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Self-test: a small synthetic circuit (does NOT require the real puzzle
# netlist), exercising reset, clocking, and combinational settle together.
# Circuit: Q <- (in_a AND in_b) on each rising clk, async reset to 0 via rst_n.
# ---------------------------------------------------------------------------

def _synthetic_netlist():
    return {
        "ports": {
            "clk":   {"net_id": 0, "net_name": "clk", "direction": "input"},
            "rst_n": {"net_id": 1, "net_name": "rst_n", "direction": "input"},
            "in_a":  {"net_id": 2, "net_name": "in_a", "direction": "input"},
            "in_b":  {"net_id": 3, "net_name": "in_b", "direction": "input"},
            "out_q": {"net_id": 4, "net_name": "out_q", "direction": "output"},
        },
        "nets": {},
        "instances": [
            {
                "cell_type": "sky130_fd_sc_hd__and2_2",
                "instance_id": 0,
                "pins": {"A": "in_a", "B": "in_b", "VGND": "VGND", "VPWR": "VPWR", "X": "and_out"},
            },
            {
                "cell_type": "sky130_fd_sc_hd__dfrtp_2",
                "instance_id": 1,
                "pins": {"CLK": "clk", "D": "and_out", "Q": "out_q", "RESET_B": "rst_n",
                         "VGND": "VGND", "VPWR": "VPWR"},
            },
        ],
    }


def self_test():
    print("=== Stage 11 Self-Test: synthetic AND-gate + DFF circuit ===\n")
    sim = Simulator(_synthetic_netlist())

    # 1. Assert reset with clk low -- Q should go to 0 immediately, async.
    sim.step(rst_n=False, clk=False, in_a=True, in_b=True)
    q = sim.read("out_q")
    print(f"After async reset (rst_n=0): out_q = {q}  (expected False)")
    assert q == False

    # 2. Release reset, clk still low -- D=(1&1)=1, but no edge yet, Q should hold at 0.
    sim.step(rst_n=True, clk=False)
    q = sim.read("out_q")
    print(f"Reset released, clk still low: out_q = {q}  (expected False, no edge yet)")
    assert q == False

    # 3. Rising edge -- Q should latch D = (in_a AND in_b) = 1.
    sim.step(clk=True)
    q = sim.read("out_q")
    print(f"Rising clk edge: out_q = {q}  (expected True, latched A&B)")
    assert q == True

    # 4. Change inputs while clk high -- Q should NOT change (no new edge).
    sim.step(in_a=False)
    q = sim.read("out_q")
    print(f"Inputs changed mid-high-phase: out_q = {q}  (expected True, holds)")
    assert q == True

    # 5. Falling edge, then rising edge again -- Q should now latch new D = (0&1) = 0.
    sim.step(clk=False)
    sim.step(clk=True)
    q = sim.read("out_q")
    print(f"Next rising edge with in_a=0: out_q = {q}  (expected False)")
    assert q == False

    print("\n✓ All self-test assertions passed.")


if __name__ == "__main__":
    self_test()