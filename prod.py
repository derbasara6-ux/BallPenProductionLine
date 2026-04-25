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
    """Quality grade assigned by inspection stations."""
    OK = auto()
    DEFECTIVE = auto()


@dataclass
class Component:
    """A generic part that goes into a pen (barrel, tip, cartridge, cap)."""
    name: str
    serial: int
    quality: Quality = Quality.OK


@dataclass
class BallPen:
    """Finished or in-progress pen: a composition of components."""
    serial: int
    barrel: Optional[Component] = None
    tip: Optional[Component] = None
    cartridge: Optional[Component] = None
    cap: Optional[Component] = None
    quality: Quality = Quality.OK
    packaged: bool = False

    def is_complete(self) -> bool:
        """Has every component been installed?"""
        return all([self.barrel, self.tip, self.cartridge, self.cap])


# ---------------------------------------------------------------------------
# 2. Stations: each step on the line is its own class
# ---------------------------------------------------------------------------

class Station(ABC):
    """Abstract base for any station on the line.

    Every concrete station must implement `process`, which takes one item
    from its input and returns the (possibly transformed) item, or None
    if the item should be discarded (e.g., failed QC).
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
        """Helper: simulate manufacturing variance."""
        return (
            Quality.DEFECTIVE
            if random.random() < self.defect_rate
            else Quality.OK
        )

    def log(self, message: str) -> None:
        print(f"[{self.name:<18}] {message}")


class ComponentMaker(Station):
    """Manufactures one type of component (barrels, tips, ...)."""

    def __init__(self, component_name: str, defect_rate: float = 0.05):
        super().__init__(name=f"Make {component_name}", defect_rate=defect_rate)
        self.component_name = component_name
        self._counter = 0

    def process(self, _ignored=None) -> Component:
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
    """Discards defective components before they reach assembly."""

    def process(self, item: Component) -> Optional[Component]:
        self.processed += 1
        if item.quality is Quality.DEFECTIVE:
            self.rejected += 1
            self.log(f"REJECT {item.name}#{item.serial}")
            return None
        self.log(f"pass   {item.name}#{item.serial}")
        return item


class AssemblyStation(Station):
    """Combines four good components into a single pen."""

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
    """Final QC: a pen must be complete *and* non-defective."""

    def process(self, pen: BallPen) -> Optional[BallPen]:
        self.processed += 1
        if not pen.is_complete() or pen.quality is Quality.DEFECTIVE:
            self.rejected += 1
            self.log(f"REJECT Pen#{pen.serial}")
            return None
        self.log(f"pass   Pen#{pen.serial}")
        return pen


class Packaging(Station):
    """Wraps the pen — the last step before shipping."""

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
    """Runs the whole line for a target number of pens."""

    COMPONENT_NAMES = ("barrel", "tip", "cartridge", "cap")

    def __init__(self):
        # One maker + one QC per component
        self.makers = {n: ComponentMaker(n) for n in self.COMPONENT_NAMES}
        self.qcs = {n: QualityControl(name=f"QC {n}") for n in self.COMPONENT_NAMES}
        # Queues hold *good* components waiting for assembly
        self.bins: dict[str, Deque[Component]] = {
            n: deque() for n in self.COMPONENT_NAMES
        }
        self.assembly = AssemblyStation()
        self.final_qc = FinalInspection(name="Final QC")
        self.packaging = Packaging()
        self.shipped: List[BallPen] = []

    # -- internal helpers ----------------------------------------------------

    def _refill_bins(self) -> None:
        """Make + inspect components until each bin has at least one."""
        for name in self.COMPONENT_NAMES:
            while not self.bins[name]:
                raw = self.makers[name].process()
                inspected = self.qcs[name].process(raw)
                if inspected is not None:
                    self.bins[name].append(inspected)

    def _assemble_one(self) -> Optional[BallPen]:
        parts = {n: self.bins[n].popleft() for n in self.COMPONENT_NAMES}
        pen = self.assembly.process(parts)
        pen = self.final_qc.process(pen)
        if pen is None:
            return None
        return self.packaging.process(pen)

    # -- public API ----------------------------------------------------------

    def run(self, target: int) -> None:
        """Produce `target` shippable pens."""
        print(f"\n=== Starting production: target = {target} pens ===\n")
        while len(self.shipped) < target:
            self._refill_bins()
            pen = self._assemble_one()
            if pen is not None:
                self.shipped.append(pen)
        self._report()

    def _report(self) -> None:
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