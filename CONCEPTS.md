# Concepts — A Walkthrough of Every Idea Behind the Pipeline

This document explains the *ideas* behind each stage of the pipeline, in
the order they appear — not the code, not the bugs hit along the way, just
"what is this stage actually doing, and why does it work." If you've never
opened a chip layout file before, start here.

---

## The Core Problem

A GDS file is just shapes on layers. Rectangles and polygons on
differently-numbered layers, sitting in physical space. It's pure
geometry — the same way a photograph of a circuit board doesn't come with
labels telling you which trace is which signal. Everything the chip does
is encoded in there somewhere, but nothing is named. The entire pipeline
exists to answer one question, one layer of abstraction at a time: *what
is actually wired to what, and what does that wiring compute?*

---

## Stage 1 — Know What You're Looking At (Instances)

First question: what standard cells were placed, and where?

A chip's layout doesn't contain raw transistors scattered everywhere — it
contains *references* to pre-built cells (NAND gates, muxes, flip-flops)
from a standard cell library, each placed at some (x, y) position, possibly
rotated or mirrored. Stage 1 just walks through every one of those
references and notes: this is a NAND2, sitting here, at this rotation.

This is like looking at a circuit board and identifying "there's a
resistor here, a capacitor there" — recognizing components and their
locations, without yet knowing how any of them are wired together.

---

## Stage 2 — Know the Anatomy of Each Component (Pin Definitions)

Second question: for a given cell *type*, where exactly do its pins sit?

Every standard cell has a fixed, known internal layout — its pins sit at
fixed positions relative to the cell's own corner, regardless of where
that cell eventually gets placed on the chip. This is extracted once, per
cell type, from labels embedded in the cell's own definition.

This is like a datasheet for a resistor telling you "pin 1 is on the
left, pin 2 is on the right" — true no matter where you eventually solder
that resistor onto a board.

---

## Stage 3 — Merge Position + Anatomy (Absolute Pin Coordinates)

Combine Stage 1 and Stage 2: if a gate sits at position (150, 200) and its
"A" pin is normally at relative offset (1.6, 1.2) inside that cell's own
frame — where does "A" physically sit on the *whole chip*?

Take the relative offset, apply the instance's own transform (mirror
first, if reflected, then rotate, then translate to the final position —
order matters), and you get the absolute location of every pin on every
gate, everywhere on the chip.

Now you know exactly where pin 1 of *that specific* resistor sits on the
real board, not just "on the left side of a generic resistor."

---

## Stage 4a — Find the Wires (Metal Routing)

Separately from the gates themselves, the layout also contains the actual
copper — metal wires that connect components together, spread across
several stacked layers (met1, met2, met3...).

**Why multiple stacked layers exist at all:** a chip is 2D on paper but
real wires can't all live on one plane without crossing each other
constantly. Stacking several metal layers, connected vertically where
needed, is how a chip routes thousands of signals through a small area
without every wire physically colliding with every other wire — the same
reason a multi-layer PCB exists instead of a single-sided one, just far
denser.

Stage 4a extracts all of this raw geometry: every polygon, on every metal
layer. This is looking at the traces on a board — the lines that snake
between components. You don't yet know which trace belongs to which
signal.

---

## Stage 4b — Find the Vertical Connections (Vias / Contacts)

If a wire needs to move from one metal layer to another, it does so
through a **via** — a small vertical connection punched through the
insulation between layers. Without vias, each metal layer would be
electrically isolated from every other layer; vias are what let a signal
travel from met1 up to met2, across, then back down to met1 somewhere
else.

Stage 4b extracts every via/contact position on every layer transition —
each one a single point marking "these two layers are electrically joined
right here."

---

## Stage 5 — Figure Out Which Wires Are the Same Net (Connectivity Grouping)

Two pieces of metal that touch (on the same layer) or are joined by a via
(across layers) are electrically the same **net** — the same signal,
physically made of possibly many polygons spread across several layers.

**The algorithm: Union-Find.** This is just a way of tracking "which group
does this thing belong to," efficiently. Every shape starts in its own
group. Whenever two shapes are found to touch (or be via-connected),
merge their groups into one. Keep doing this across every shape and every
via, and what's left when you're done is the true set of electrical nets.

**Why this needs careful scoping, not just "merge anything that touches":**
Union-Find is *transitive* — if shape A merges with B, and B merges with
C, then A and C end up in the same group too, even if A and C never
touch each other directly. That's exactly correct for real wiring (a
signal really is one continuous net across however many segments it
takes), but it's dangerous if the merge rule is too loose: one small
overlap in the wrong place can chain the *entire chip* into a single
net through a long accidental sequence of touches, the same way one
domino falling can knock over a chain far longer than the domino that
started it.

**Why some layers merge differently than others.** General routing metal
(met1–met5) is meant to span the whole chip freely, so it's merged
chip-wide. But *local interconnect* (li1) lives inside each standard
cell's own small footprint, packed densely — merging it chip-wide risks
exactly the domino-chain problem above. Real chip manufacturing already
has a name for the fix: **abutment offset zones** — standard cells are
deliberately laid out with a small gap at their edges specifically so one
cell's internal routing never accidentally touches its neighbor's,
because manufacturing itself isn't perfectly precise, and this margin
exists to guarantee that unrelated features stay unrelated even under
worst-case alignment error. That's also why minimum-spacing design rules
exist at all: two features that aren't meant to touch need to *stay* not
touching even when the manufacturing process wobbles slightly. Scoping
li1's merge to each cell's own footprint mirrors that real physical
design intent directly.

Tracing every copper trace with your finger to see which parts are
actually one continuous wire, even as it zigzags across layers — that's
this whole stage, done algorithmically instead of by hand.

---

## Stage 6a — Connect Pins to Nets (Point-in-Polygon)

Now merge Stage 3 (where every pin physically sits) with Stage 5 (which
blob of copper occupies which region of space): for every pin, check
which net's geometry that pin's coordinate falls inside.

The underlying test — "is this point inside this shape" — is a classic,
simple geometric operation (point-in-polygon), just applied once per pin,
against the correct layer's geometry only (a pin on li1 must be checked
against li1 shapes, not met1 shapes — comparing across layers gives
nonsense results, since two shapes that happen to overlap when flattened
onto one 2D view might be on completely different physical layers with no
real connection at all).

Now you know: this resistor's pin 1 and that capacitor's pin 2 are both
touching the same copper trace — i.e., they're wired together.

---

## Stage 6b/6c — Naming and Emitting the Netlist

A **netlist** is just a formal, textual description of a circuit: declare
every net as a wire, then list every gate instance with which of its pins
connects to which named wire. This is the actual logical description of
the circuit — the same information a chip designer's original source code
would have contained, recovered purely from geometry, with no access to
that original source.

---

## Stage 7 — Is the Clock Tree Actually Connected? (Graph Reachability / BFS)

Every flip-flop in a synchronous circuit only updates on a clock edge — it
sits there ignoring its input entirely until `clk` ticks. If even one
flip-flop's clock path is broken, that flip-flop is frozen forever: not
wrong, just silently stuck, and the rest of the simulation will still run
and still produce plausible-looking, quietly incorrect output.

The clock doesn't reach all the flip-flops from one pin directly — one
pin can't drive that many loads cleanly, so it fans out through a tree of
buffer cells, each re-driving the signal to a manageable number of
children, the same way a water main splits into branch pipes before
reaching individual taps.

**Breadth-first search (BFS)** is the right tool for exactly this
question: start at the clock's own pad, and systematically expand
outward — every buffer that node feeds, every buffer *those* feed, and so
on — marking every flip-flop the walk actually touches along the way. At
the end you get one hard, binary answer per flip-flop: reached, or not.
No sampling, no probability — either a path exists through the graph, or
it doesn't.

---

## Stage 8 — Reading the Chip's Own Labels (Port Identification)

Top-level signal names (`clk`, `success`, etc.) aren't guessed at — they're
searched for directly as literal text labels physically embedded in the
GDS at the chip's edges, the same labels a fabrication engineer would use
to know which physical pad is which signal. Each label's coordinate is
then resolved to a net using the exact same point-in-polygon logic from
Stage 6a. This is the chip identifying its own interface, directly, with
no inference required.

---

## Stage 9 — Final Assembly

Combines everything into one clean, self-consistent netlist: real port
names with correct directions, every net given a readable name, every
instance's pins pointing at those names. This is the single artifact
every later stage builds on.

---

## Stage 10 — Teaching the Computer What Each Gate *Does* (Boolean Logic)

A netlist tells you *what's wired to what*. It says nothing about what
each gate actually *computes*. That's a separate, purely logical problem:
given a gate's inputs, what's its output?

Standard cell libraries name their gates in a way that directly encodes
their logic. A gate named `a21o` is an **AND-OR** structure: AND two of
its inputs together, then OR that result with a third input. A gate named
`o21a` is the reverse shape, **OR-AND**: OR two inputs, then AND with a
third. The "i" suffix (`a21oi`) means the whole thing gets inverted at the
very end. This isn't arbitrary — it directly reflects **sum-of-products**
and **product-of-sums** boolean algebra, the two standard ways to build
any boolean function out of AND/OR/NOT. Once you know the naming
convention, you can write a small number of generic *shape* builders
(AND-then-OR, OR-then-AND, plain N-input) instead of hand-writing dozens
of near-identical functions individually — which also means far less
surface area for a copy-paste mistake to hide in.

---

## Stage 11 — Simulating the Circuit (Gate-Level Simulation)

A synchronous digital circuit updates in a strict two-phase pattern, once
per clock cycle:

**Phase 1 — combinational settle.** Every ordinary gate (AND, OR, mux,
etc.) computes its output purely from its current inputs, and that output
feeds into other gates, and so on. Since there are no loops in this part
of the circuit (a value never depends on itself, only on flip-flop outputs
and primary inputs from *before* this cycle), this settles to one stable
answer by simply propagating values forward until nothing changes —- no
guessing required, because the structure is a directed graph with no
cycles.

**Phase 2 — synchronous update.** *Only* on the clock edge, every
flip-flop looks at whatever its input settled to in Phase 1, and adopts
that as its new stored value — unless its reset/set control pin says
otherwise, in which case it snaps to a fixed value regardless of its
input. This is the only place state actually changes; everything else is
pure, stateless computation re-evaluated fresh every cycle.

Modeling reset this way — as an explicit, controllable phase you trigger
deliberately — rather than relying on a general-purpose hardware
simulator's own internal timing rules, is what makes the whole thing
fully predictable.

---

## Stage 12 — Driving the Circuit Like Real Hardware (The Cycle Driver)

A raw simulator can compute one step at a time, but real usage means a
sequence: assert reset, release it, then toggle the clock repeatedly while
feeding real input values on each rising edge. The cycle driver is just
that usage pattern, wrapped up so you can say "run N cycles with these
inputs" instead of manually sequencing every clock edge by hand.

---

## Stage 13 — Proving the Simulator Is Actually Correct (VCD Cross-Validation)

A **VCD file** (Value Change Dump) is a standard, plain-text format for
recording exactly what happened on real hardware over time: every signal,
every timestamp, every value change. It's essentially a black-box
recording of ground truth — what the real chip *actually did* when fed a
specific input.

Replaying that real recorded sequence through the self-built simulator and
checking whether the outputs match, bit for bit, at every single cycle, is
the strongest kind of validation available here: not "does this look
internally consistent," but "does this match reality." A self-consistent
simulator can still be wrong in a way that never contradicts itself; a
simulator that reproduces real, independently-recorded hardware behavior
exactly has actually been tested against the real world.

---

## Stage 14 — Finding the Register (Structural Graph Tracing)

A **shift register** is a chain of memory bits where, each cycle, every
bit either grabs a fresh incoming value or holds what it already had,
controlled by a shared select signal. The structural signature to look for
in gate-level wiring is a small selector (a mux) whose one input is wired
back to its *own* flip-flop's stored value — that self-loop *is* the
"hold" path; the other input is the "load something new" path. Following
that pattern from one stage to the next — this stage's stored value
becomes the next stage's "old value" input — traces out the whole chain,
structurally, from the actual wiring, rather than by inference or
guesswork.

---

## Stage 15 — Why Brute Force Sometimes Isn't an Option (Combinatorial Explosion)

If a register is genuinely only 12 bits wide, trying every possible value
(4,096 of them) takes no time at all. But if the real controllable state
turns out to be much wider — say, 121 independent bits — the number of
possible combinations is 2^121, a number so large it isn't just
"slow to check," it's larger than the number of grains of sand on every
beach and desert on Earth, combined, several times over. No computer,
now or in any practical future, checks a space that size one value at a
time. Past a certain width, brute force isn't a slower tool — it's not a
tool at all.

---

## Stage 16 — Asking the Answer to Prove Itself (SAT Solving / Bounded Model Checking)

Instead of trying specific input values, leave every input bit as a
free, unknown variable, and build one large logical formula directly out
of the real circuit's own gates — this AND that, that OR this, chained
across every gate and every clocked update, from the unknown input bits
all the way out to the `success` signal. Then ask a **SAT solver**
(satisfiability solver) one question: does *any* assignment of those
unknowns make this formula true?

The solver doesn't check assignments one at a time. It works more like
solving a logic puzzle by deduction:

1. **Propagate what's forced.** If a clause only has one undecided
   variable left and everything else in it is already false, that last
   variable *must* be true — no guessing needed. Chase these forced
   consequences everywhere they lead before doing anything else.
2. **Guess, only when truly stuck.** Once propagation runs dry and
   something is still genuinely undecided, pick a value and try it —
   then go straight back to propagating off that guess.
3. **Learn from every failure.** If a guess leads to a direct
   contradiction, the solver doesn't just back up one step — it figures
   out *exactly* which earlier decisions actually caused the conflict,
   and permanently records "that specific combination can never work" as
   a brand new rule. Because real circuits are full of repeated
   structure (the same gate patterns and shared control signals appearing
   over and over), one learned rule often silently rules out enormous
   numbers of other bad guesses at once, not just the one that revealed
   it.

Applying this to a formula built from real, structured circuit logic
means the search collapses from "impossibly large" to "fraction of a
second," because the solver isn't searching — it's deducing.

**Proving uniqueness, the same way.** Once one satisfying assignment is
found, adding a rule that explicitly excludes exactly that assignment and
asking the solver to try again turns "did we find another one" into a
formal proof: if the solver comes back `UNSAT` (unsatisfiable), that's not
"didn't find one" — it's a mathematical guarantee that no other
assignment satisfies the formula at all.

---

## Stage 17 — Closing the Loop (Independent Confirmation)

A result from one tool, however confident-sounding, is still just one
tool's answer. Replaying the exact winning input through the
*separately-built* concrete simulator — the same one already validated
against real captured silicon in Stage 13 — and confirming it produces
the same result independently is what turns "the solver said sat" into
"two independently-built systems, built for different purposes, agree."
That agreement is the actual basis for trusting the final answer, not
either tool alone.
