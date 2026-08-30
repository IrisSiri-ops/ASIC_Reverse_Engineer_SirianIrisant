"""
====================================================================
PHASE 5: CYCLE DRIVER
====================================================================
Stage 12: Cycle-Accurate Driver
------------------------------------

Purpose
-------
Wraps the Stage 11 Simulator's low-level step() primitive in a realistic
clock/reset/input schedule, so callers work in terms of "cycles" (each
with an enable/I value) rather than hand-toggling clk high/low.

Historical note (net_0562)
-----------------------------
An earlier version of the recovered netlist had one net (net_0562) with
no driving instance, discovered while validating this driver against
the real design. See STATUS_net_0562.md for the full investigation.
This was resolved with strong convergent evidence and is now fixed
permanently in Stage 9's netlist assembly -- O[1] and O[4] read
correctly, along with every other output bit.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage11_simulator import Simulator, load_netlist

OUTPUT_ORDER = ["success", "O[0]", "O[1]", "O[2]", "O[3]", "O[4]", "O[5]", "O[6]", "O[7]"]


def fmt_bit(value):
    if value is None:
        return "X"
    return "1" if value else "0"


class CycleDriver:
    def __init__(self, netlist_path):
        self.netlist = load_netlist(netlist_path)
        self.sim = Simulator(self.netlist)
        self.history = []  # list of dicts: cycle, enable, I, outputs
        self._cycle_count = 0
        self._reset_done = False

    def reset(self, hold_cycles=2):
        """
        Assert rst_n low with clk low, settle, then release rst_n with
        clk still low before any clock edges occur. This is the explicit,
        fully-controlled reset sequencing that was impossible to get right
        under iverilog's UDP delta-cycle timing -- here it's just two
        ordinary steps.
        """
        self.sim.step(rst_n=False, clk=False, enable=False, I=False)
        for _ in range(hold_cycles):
            self.sim.step()  # hold reset asserted for a couple settles, belt-and-suspenders
        self.sim.step(rst_n=True, clk=False)
        self._reset_done = True

    def cycle(self, enable, I):
        """
        Run one full clock cycle: set enable/I, rising edge, falling edge.
        Records outputs as read immediately after the rising edge (the
        point at which flip-flops have just latched their new values and
        combinational logic has re-settled).
        """
        if not self._reset_done:
            raise RuntimeError("Call reset() before running cycles.")

        self.sim.step(enable=enable, I=I, clk=True)   # rising edge -- flops latch
        outputs = self.sim.read_outputs()
        self.sim.step(clk=False)                       # falling edge -- no flop change

        self._cycle_count += 1
        record = {"cycle": self._cycle_count, "enable": enable, "I": I, "outputs": outputs}
        self.history.append(record)
        return outputs

    def run_sequence(self, io_sequence):
        """
        io_sequence: list of (enable, I) tuples, one per cycle.
        Returns the full list of per-cycle output dicts.
        """
        return [self.cycle(enable, I) for enable, I in io_sequence]

    def print_waveform(self, last_n=None):
        rows = self.history if last_n is None else self.history[-last_n:]
        header = f"{'cyc':>4} {'en':>2} {'I':>2} | " + " ".join(f"{name:>8}" for name in OUTPUT_ORDER)
        print(header)
        print("-" * len(header))
        for r in rows:
            en = "1" if r["enable"] else "0"
            i = "1" if r["I"] else "0"
            out_str = " ".join(f"{fmt_bit(r['outputs'].get(name)):>8}" for name in OUTPUT_ORDER)
            print(f"{r['cycle']:>4} {en:>2} {i:>2} | {out_str}")


# ---------------------------------------------------------------------------
# Quick manual check when run directly: reset, then a handful of arbitrary
# cycles, just to confirm the driver itself behaves sanely against the real
# design (not yet a real input search -- that's Phase 7).
# ---------------------------------------------------------------------------

def main():
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)
    NETLIST_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage9_final_netlist.json")

    driver = CycleDriver(NETLIST_FILE)
    driver.reset()
    print("Reset complete.\n")

    # Arbitrary placeholder sequence -- enable held high, I alternating.
    # Not a real search yet, just exercising the driver end to end.
    test_sequence = [(True, bit % 2 == 0) for bit in range(16)]
    driver.run_sequence(test_sequence)
    driver.print_waveform()


if __name__ == "__main__":
    main()