"""
ballpen_production_line.py
==========================
A teaching example: simulate a ball-pen production line in Python.

Concepts demonstrated:
- Dataclasses for plain data (components, pens)
- Enums for fixed sets of states
- Abstract base classes (ABCs) for a common station interface
- Composition: a ProductionLine is built from Stations
- Queues to pass work between stations
- Simple statistics / quality control with randomness
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Deque, List, Optional


# ---------------------------------------------------------------------------
# 1. Domain model: what *is* a ball pen?
# ---------------------------------------------------------------------------

class Quality(Enum):
    """Every part and every finished pen ends up tagged either OK or
    DEFECTIVE. Using an Enum here instead of strings or booleans means
    a typo like 'defective' vs 'Defective' would fail at import time
    rather than silently letting bad parts slip through."""
    OK = auto()
    DEFECTIVE = auto()


@dataclass
class Component:
    """A single part — could be a barrel, a tip, a cartridge, or a cap.
    The serial number lets us trace individual parts through the line in
    the log output, which is handy for debugging weird behavior."""
    name: str
    serial: int
    quality: Quality = Quality.OK


@dataclass
class BallPen:
    """A pen, finished or in-progress. Built up by Assembly attaching
    each of the four required components, then stamped with its own
    overall quality grade (assembly itself can fail even if every part
    was good). The packaged flag flips to True once Packaging touches it."""
    serial: int
    barrel: Optional[Component] = None
    tip: Optional[Component] = None
    cartridge: Optional[Component] = None
    cap: Optional[Component] = None
    quality: Quality = Quality.OK
    packaged: bool = False

    def is_complete(self) -> bool:
        """True only if all four component slots have been filled in.
        Used by Final QC to catch any pen that somehow got here missing
        a part — shouldn't happen in normal flow, but it's cheap insurance."""
        return all([self.barrel, self.tip, self.cartridge, self.cap])


# ---------------------------------------------------------------------------
# 2. Stations: each step on the line is its own class
# ---------------------------------------------------------------------------

class Station(ABC):
    """The shared shape every station on the line follows.

    Each station has a name (for logging), a defect rate (probability
    that whatever it produces comes out flawed), and a pair of running
    counters. The only thing subclasses must define is `process` —
    everything else is provided here so individual stations stay tiny.
    """

    def __init__(self, name: str, defect_rate: float = 0.0):
        self.name = name
        self.defect_rate = defect_rate
        self.processed = 0
        self.rejected = 0

    @abstractmethod
    def process(self, item):
        ...

    def _maybe_defect(self) -> Quality:
        """Roll the dice once. Returns DEFECTIVE with probability equal
        to this station's defect_rate, otherwise OK. Centralising this
        keeps the randomness in one place so every station behaves
        consistently."""
        return (
            Quality.DEFECTIVE
            if random.random() < self.defect_rate
            else Quality.OK
        )

    def log(self, message: str) -> None:
        print(f"[{self.name:<18}] {message}")


class ComponentMaker(Station):
    """Manufactures one specific kind of component. There are four of
    these on the line (one per component name) running in parallel.
    Each maker keeps its own serial counter so barrels and tips have
    independent numbering."""

    def __init__(self, component_name: str, defect_rate: float = 0.05):
        super().__init__(name=f"Make {component_name}", defect_rate=defect_rate)
        self.component_name = component_name
        self._counter = 0

    def process(self, _ignored=None) -> Component:
        # The argument is ignored — makers don't have an input, they just
        # produce parts on demand. We accept _ignored only to satisfy the
        # Station interface contract.
        self._counter += 1
        self.processed += 1
        part = Component(
            name=self.component_name,
            serial=self._counter,
            quality=self._maybe_defect(),
        )
        self.log(f"produced {part.name}#{part.serial} -> {part.quality.name}")
        return part


class QualityControl(Station):
    """The first inspection step. Accepts a freshly-made component and
    either passes it through (returning it unchanged) or rejects it
    (returning None). The line treats None as 'this never happened' —
    rejected parts simply don't make it to the bins."""

    def process(self, item: Component) -> Optional[Component]:
        self.processed += 1
        if item.quality is Quality.DEFECTIVE:
            self.rejected += 1
            self.log(f"REJECT {item.name}#{item.serial}")
            return None
        self.log(f"pass   {item.name}#{item.serial}")
        return item


class AssemblyStation(Station):
    """Takes one of each component type and snaps them together into a
    pen. There's a small chance (defect_rate) that assembly itself goes
    wrong even when every input part was perfect — that's caught later
    by Final QC."""

    def __init__(self, defect_rate: float = 0.02):
        super().__init__(name="Assembly", defect_rate=defect_rate)
        self._counter = 0

    def process(self, parts: dict) -> BallPen:
        self._counter += 1
        self.processed += 1
        pen = BallPen(
            serial=self._counter,
            barrel=parts["barrel"],
            tip=parts["tip"],
            cartridge=parts["cartridge"],
            cap=parts["cap"],
            quality=self._maybe_defect(),  # assembly itself can fail
        )
        self.log(f"assembled Pen#{pen.serial} -> {pen.quality.name}")
        return pen


class FinalInspection(Station):
    """The last gate before packaging. A pen has to clear two checks: it
    must have all four components installed, and its overall quality flag
    must be OK. Anything that fails either check gets dropped."""

    def process(self, pen: BallPen) -> Optional[BallPen]:
        self.processed += 1
        if not pen.is_complete() or pen.quality is Quality.DEFECTIVE:
            self.rejected += 1
            self.log(f"REJECT Pen#{pen.serial}")
            return None
        self.log(f"pass   Pen#{pen.serial}")
        return pen


class Packaging(Station):
    """The finishing touch. No defect rate here — packaging is assumed
    to never fail. Just flips the pen's `packaged` flag to True and
    sends it on its way."""

    def __init__(self):
        super().__init__(name="Packaging")

    def process(self, pen: BallPen) -> BallPen:
        self.processed += 1
        pen.packaged = True
        self.log(f"packaged Pen#{pen.serial}")
        return pen


# ---------------------------------------------------------------------------
# 3. The production line: orchestrates the stations
# ---------------------------------------------------------------------------

class ProductionLine:
    """The whole factory wired up as one object. Holds every station,
    every bin, and the list of finished pens. Calling .run(target)
    drives the line until that many shippable pens have come off it."""

    COMPONENT_NAMES = ("barrel", "tip", "cartridge", "cap")

    def __init__(self):
        # One maker and one QC station per component type. Using dicts
        # keyed by component name makes it easy to fetch the right pair
        # in the loops below.
        self.makers = {n: ComponentMaker(n) for n in self.COMPONENT_NAMES}
        self.qcs = {n: QualityControl(name=f"QC {n}") for n in self.COMPONENT_NAMES}
        # Bins are FIFO queues of inspected, known-good components waiting
        # to be pulled into Assembly. A deque is used because it gives O(1)
        # append-on-the-right and popleft-from-the-left, matching how a
        # real conveyor belt feeds parts in the order they were made.
        self.bins: dict[str, Deque[Component]] = {
            n: deque() for n in self.COMPONENT_NAMES
        }
        self.assembly = AssemblyStation()
        self.final_qc = FinalInspection(name="Final QC")
        self.packaging = Packaging()
        self.shipped: List[BallPen] = []

    # -- internal helpers ----------------------------------------------------

    def _refill_bins(self) -> None:
        """Make sure every bin has at least one part queued up before we
        try to assemble. For each empty bin, we keep producing and
        inspecting parts until one survives QC. This is what causes
        defective components to inflate the 'made' count well above the
        number of pens that eventually ship."""
        for name in self.COMPONENT_NAMES:
            while not self.bins[name]:
                raw = self.makers[name].process()
                inspected = self.qcs[name].process(raw)
                if inspected is not None:
                    self.bins[name].append(inspected)

    def _assemble_one(self) -> Optional[BallPen]:
        """One full attempt at making a pen: pull one of each component
        from the bins, hand them to Assembly, run the result through
        Final QC, and if it survives, package it. Returns None if the
        pen failed Final QC — the caller is responsible for noticing
        and trying again."""
        parts = {n: self.bins[n].popleft() for n in self.COMPONENT_NAMES}
        pen = self.assembly.process(parts)
        pen = self.final_qc.process(pen)
        if pen is None:
            return None
        return self.packaging.process(pen)

    # -- public API ----------------------------------------------------------

    def run(self, target: int) -> None:
        """Keep running the line until `target` pens have shipped.
        Each iteration: top up the bins, try to assemble one pen, and
        if it survived, add it to the shipped list. Failed assemblies
        just go around again."""
        print(f"\n=== Starting production: target = {target} pens ===\n")
        while len(self.shipped) < target:
            self._refill_bins()
            pen = self._assemble_one()
            if pen is not None:
                self.shipped.append(pen)
        self._report()

    def _report(self) -> None:
        """Dump per-station stats once the run is done. Useful for
        sanity-checking that defect rates are roughly what you set
        and for spotting any station that's processing way more or
        fewer items than expected."""
        print("\n=== Production report ===")
        all_stations: list[Station] = [
            *self.makers.values(),
            *self.qcs.values(),
            self.assembly,
            self.final_qc,
            self.packaging,
        ]
        for s in all_stations:
            print(
                f"{s.name:<18} processed={s.processed:<4} rejected={s.rejected}"
            )
        print(f"\nShipped pens: {len(self.shipped)}")


# ---------------------------------------------------------------------------
# 4. Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    random.seed(42)  # reproducible classroom output
    ProductionLine().run(target=5)