# Resources & Documentation

Literature, documentation, and tooling references that were directly relevant to
each phase of this pipeline -- compiled after the fact, but reflecting exactly
where each would have been useful during development.

---

## Phase 0-1: Extraction (GDS -> geometry -> instances)

**GDSII format and gdspy**
- [gdspy documentation](https://gdspy.readthedocs.io/) -- the library used throughout
  Stages 1-4a. Covers cell reference traversal, `get_polygons(by_spec=True)`
  recursion behavior, and hierarchy/vertex-count quirks.

**Sky130 layer numbering, cell heights, layer stack**
- [SkyWater SKY130 PDK docs -- PDK Contents](https://skywater-pdk.readthedocs.io/en/main/contents.html)
- [VLSIDA Chip Tutorials -- Sky130](https://github.com/VLSIDA/chip-tutorials/blob/main/sky130.md) --
  states the exact layer stack (`met5 -> via4 -> met4 -> ... -> li1`) and
  explicitly notes **li1 is not a general routing layer** -- exactly the lesson
  learned the hard way in the warmup (chip-wide li1 merge caused catastrophic
  over-merging). Would have flagged this risk upfront.

---

## Phase 3: Cell-behavior library (boolean logic definitions)

The phase where documentation would have saved the most time, since gate
polarity was inferred from naming convention alone rather than looked up
directly.

- **[sky130_fd_sc_hd README](https://sky130-unofficial.readthedocs.io/en/latest/contents/libraries/sky130_fd_sc_hd/README.html)** --
  actual per-cell logic descriptions, e.g. literally stating "2-input AND into
  first input of 4-input OR" for `a21o`-family cells. Would have let every
  gate's boolean identity be looked up directly instead of derived from naming
  pattern -- including resolving the `o2bb2a_2` low-confidence flag outright.
- [ChipVerify -- Standard Cell Libraries](https://chipverify.com/rtl-synthesis/standard-cell-libraries) --
  decodes the `sky130_fd_sc_XX__YYYY_Z` naming scheme piece by piece.
- [Wikipedia -- AND-OR-Invert](https://en.wikipedia.org/wiki/AND-OR-invert) and
  [Wikipedia -- Standard cell](https://en.wikipedia.org/wiki/Standard_cell) --
  background on why AOI/OAI gates exist and how they map to sum-of-products
  logic, the theoretical basis for the `sop_gate`/`pos_gate` DSL in Stage 10.

---

## Phase 4/5: Extraction methodology (geometry -> connectivity -> netlist)

- **ReGDS: A Reverse Engineering Framework from GDSII to Gate-level Netlist**
  (Rajarathnam, Lin, Jin, Pan -- HOST 2020) -- directly relevant to the Stage
  4/5 problem: extracting a gate-level netlist from raw GDS geometry via
  LVS-style connectivity, in exactly the "no power/schematic info available"
  scenario this project was in.
- [Shapely STRtree docs](https://shapely.readthedocs.io/en/stable/strtree.html) --
  the spatial-query engine underlying the entire Stage 5 connectivity merge;
  clarifies `query()` return semantics and buffering behavior.

---

## Phase 4 (independent cross-check): KLayout

- [KLayout `LayoutToNetlist` class reference](https://www.klayout.de/doc/code/class_LayoutToNetlist.html) --
  the exact API used for the independent connectivity cross-check on
  net_0562. Reading this *before* building that script would likely have
  avoided the `dtrans`/`trans` coordinate confusion that slowed that
  investigation down.
- [KLayout Python module overview](https://www.klayout.org/klayout-pypi/) --
  has the working code pattern (`import klayout.db as db`) eventually used.

---

## Phase 6: VCD validation

- [Value change dump -- Wikipedia](https://en.wikipedia.org/wiki/Value_change_dump) --
  overview of the IEEE 1364 VCD format.
- [zipcpu -- "Writing your own VCD File"](https://zipcpu.com/blog/2017/07/31/vcd.html) --
  informal but clear reference for the exact scalar/vector value-change
  syntax (`0!`, `b1010100 %`) the Stage 13 parser had to reverse-engineer
  from the raw file.

---

## Phase 7: Symbolic search (Z3 / SAT-SMT)

- [Z3py official tutorial (Microsoft)](https://microsoft.github.io/z3guide/programming/Z3%20Python%20-%20Readonly/Introduction/) --
  the core `Solver()`, `add()`, `check()`, `model()` pattern used in Stage 16.
- [Getting Started with Z3 Python](https://mintlify.wiki/Z3Prover/z3/bindings/python/getting-started) --
  covers the `push()`/`pop()` pattern, useful for the "block a solution and
  re-solve" technique used to prove the answer's uniqueness.
- [CMU 15-414 -- Lecture Notes on Bounded Model Checking](https://www.cs.cmu.edu/~15414/s23/s22/lectures/17-bmc.pdf) --
  the formal name for what Stage 16 does: unrolling a sequential circuit's
  transition relation over a fixed number of cycles into a single formula.
  Worth reading early for the vocabulary alone ("bounded model checking"),
  since it would have made this approach easier to find and name from the
  start rather than arrived at independently.

---

## General background (useful throughout)

- [Jane Street ASIC reverse-engineering puzzle blog post](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/) --
  the puzzle's own framing and hints.
- [Advent of FPGA 2025 results](https://blog.janestreet.com/advent-of-fpga-challenge-2025-results/) --
  Jane Street's prior hardware challenge; informed the decision to prioritize
  a fully self-made pipeline and honest documentation of the debugging
  process over a faster, more conventional toolchain-based approach.
