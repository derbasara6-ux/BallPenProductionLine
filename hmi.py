"""
hmi.py
======
Tkinter HMI for the ball-pen production line.

Features:
  - Start / Stop controls
  - Production speed at 1/10 of original (STEP_DELAY per stage)
  - Pipeline stage indicator — same workflow as anim.py, station boxes
    light up in the component's colour as work passes through them
  - Live counters: assembled pens and total rejects
  - Rejection log: item, station, and reason for every reject

Run:
    python hmi.py
"""

from __future__ import annotations

import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(__file__))
from prod import ProductionLine

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
BG     = "#1a2332"
PANEL  = "#243044"
ACCENT = "#00b4d8"
GREEN  = "#2dc653"
RED    = "#e63946"
AMBER  = "#f4a261"
FG     = "#e0e8f0"
FG_DIM = "#7a8fa8"
HEADER = "#0d1b2a"

COMP_COLORS = {          # same as anim.py
    "barrel":    "#3498db",
    "tip":       "#9b59b6",
    "cartridge": "#2ecc71",
    "cap":       "#e74c3c",
    "pen":       "#f39c12",
}

# ---------------------------------------------------------------------------
# Pipeline canvas layout  (mirrors anim.py station positions)
# ---------------------------------------------------------------------------
_CW,  _CH    = 650, 168   # canvas width / height in pixels
_BHW, _BHH   = 30,  13   # box half-width / half-height  → 60 × 26 px per box

_LANE_Y = {"barrel": 26, "tip": 68, "cartridge": 110, "cap": 152}
_CTR_Y  = 89              # (26 + 152) / 2  — vertical centre for downstream row

_X_MAKE  =  50
_X_QC    = 145
_X_BIN   = 240
_X_ASSM  = 345
_X_FQC   = 435
_X_PACK  = 520
_X_SHIP  = 610

# ---------------------------------------------------------------------------
# Timing  — each stage takes STEP_DELAY seconds, giving ~1/10 original speed
# ---------------------------------------------------------------------------
STEP_DELAY = 0.40         # seconds per stage; full happy-path ≈ 17 × 0.40 s

# ---------------------------------------------------------------------------
# Internal event protocol  (production thread → UI thread via queue)
# ---------------------------------------------------------------------------
EVT_ASSEMBLED = "assembled"
EVT_REJECTED  = "rejected"
EVT_STAGE     = "stage"
EVT_STATUS    = "status"
EVT_STOPPED   = "stopped"


# ---------------------------------------------------------------------------
# Instrumented production line
# ---------------------------------------------------------------------------

class InstrumentedLine(ProductionLine):
    """ProductionLine that emits stage/counter events and respects a stop flag."""

    def __init__(self, event_queue: queue.Queue, stop_event: threading.Event):
        super().__init__()
        self._q    = event_queue
        self._stop = stop_event

    def _stage(self, key: str, component: str) -> None:
        """Post a stage-highlight event then sleep for STEP_DELAY."""
        if not self._stop.is_set():
            self._q.put({"type": EVT_STAGE, "stage": key, "component": component})
            time.sleep(STEP_DELAY)

    def _refill_bins(self) -> None:
        for name in self.COMPONENT_NAMES:
            while not self.bins[name]:
                if self._stop.is_set():
                    return
                self._stage(f"make_{name}", name)
                raw = self.makers[name].process()

                self._stage(f"qc_{name}", name)
                inspected = self.qcs[name].process(raw)

                if inspected is None:
                    self._q.put({
                        "type":    EVT_REJECTED,
                        "item":    f"{name.capitalize()} #{raw.serial}",
                        "station": f"QC – {name}",
                        "reason":  "Defective component",
                    })
                else:
                    self._stage(f"bin_{name}", name)
                    self.bins[name].append(inspected)

    def _assemble_one(self):
        if self._stop.is_set():
            return None

        self._stage("assembly", "pen")
        parts  = {n: self.bins[n].popleft() for n in self.COMPONENT_NAMES}
        pen    = self.assembly.process(parts)

        self._stage("final_qc", "pen")
        pen_ok = self.final_qc.process(pen)
        if pen_ok is None:
            self._q.put({
                "type":    EVT_REJECTED,
                "item":    f"Pen #{pen.serial}",
                "station": "Final QC",
                "reason":  "Assembly defect",
            })
            return None

        self._stage("packaging", "pen")
        result = self.packaging.process(pen_ok)
        self._q.put({"type": EVT_ASSEMBLED, "serial": result.serial})

        self._stage("shipped", "pen")
        return result

    def run_until_stopped(self) -> None:
        self._q.put({"type": EVT_STATUS, "msg": "● Running"})
        while not self._stop.is_set():
            self._refill_bins()
            if self._stop.is_set():
                break
            pen = self._assemble_one()
            if pen is not None:
                self.shipped.append(pen)
        self._q.put({
            "type": EVT_STATUS,
            "msg":  f"■ Stopped  —  {len(self.shipped)} pens shipped",
        })
        self._q.put({"type": EVT_STOPPED})


# ---------------------------------------------------------------------------
# HMI window
# ---------------------------------------------------------------------------

class HMI(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Ball Pen Production Line — HMI")
        self.configure(bg=BG)
        self.resizable(False, False)

        self._q              : queue.Queue             = queue.Queue()
        self._stop_event                               = threading.Event()
        self._thread         : threading.Thread | None = None
        self._n_assembled    = 0
        self._n_rejected     = 0
        self._active_stage   : str | None              = None
        self._stage_items    : dict[str, tuple]        = {}  # key → (rect_id, text_id)

        self._build_ui()
        self._poll()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Title bar ──────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=HEADER, pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="BALL PEN PRODUCTION LINE — HMI",
            bg=HEADER, fg=ACCENT,
            font=("Courier New", 15, "bold"),
        ).pack()

        # ── Counters + controls ────────────────────────────────────────
        mid = tk.Frame(self, bg=BG, padx=20, pady=14)
        mid.pack(fill="x")

        self._assembled_var = tk.StringVar(value="0")
        self._rejected_var  = tk.StringVar(value="0")

        self._counter_tile("Assembled Pens", self._assembled_var, GREEN, mid, col=0)
        self._counter_tile("Total Rejects",  self._rejected_var,  RED,   mid, col=1)

        btn_col = tk.Frame(mid, bg=BG)
        btn_col.grid(row=0, column=2, padx=30)

        self._btn_start = tk.Button(
            btn_col, text="▶  START",
            bg=GREEN, fg="#000", activebackground="#22a844",
            font=("Courier New", 12, "bold"),
            width=12, relief="flat", cursor="hand2",
            command=self._start,
        )
        self._btn_start.pack(pady=5)

        self._btn_stop = tk.Button(
            btn_col, text="■  STOP",
            bg=RED, fg="#fff", activebackground="#c0303a",
            font=("Courier New", 12, "bold"),
            width=12, relief="flat", cursor="hand2",
            state="disabled",
            command=self._stop,
        )
        self._btn_stop.pack(pady=5)

        # ── Status line ────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="■ Idle")
        tk.Label(
            self, textvariable=self._status_var,
            bg=BG, fg=AMBER,
            font=("Courier New", 10),
        ).pack(anchor="w", padx=22, pady=(0, 6))

        # ── Pipeline diagram ───────────────────────────────────────────
        pipe_frame = tk.Frame(self, bg=BG)
        pipe_frame.pack(fill="x", padx=10)
        tk.Label(
            pipe_frame, text="PRODUCTION PIPELINE",
            bg=BG, fg=FG_DIM,
            font=("Courier New", 9, "bold"),
        ).pack(anchor="w", padx=10, pady=(0, 3))
        self._build_pipeline(pipe_frame)

        # ── Divider ────────────────────────────────────────────────────
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")

        # ── Rejection log ──────────────────────────────────────────────
        log_area = tk.Frame(self, bg=BG, padx=20, pady=10)
        log_area.pack(fill="both", expand=True)

        tk.Label(
            log_area, text="REJECTION LOG",
            bg=BG, fg=FG_DIM,
            font=("Courier New", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("HMI.Treeview",
                        background=PANEL, foreground=FG,
                        fieldbackground=PANEL, rowheight=22,
                        font=("Courier New", 9))
        style.configure("HMI.Treeview.Heading",
                        background=HEADER, foreground=ACCENT,
                        font=("Courier New", 9, "bold"), relief="flat")
        style.map("HMI.Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "#000")])

        cols = ("Item", "Station", "Reason")
        wrap = tk.Frame(log_area, bg=BG)
        wrap.pack(fill="both", expand=True)

        self._tree = ttk.Treeview(
            wrap, columns=cols, show="headings",
            style="HMI.Treeview", height=10,
        )
        for col, w in zip(cols, (170, 180, 260)):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, anchor="w")

        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tk.Frame(self, bg=BG, height=8).pack()

    def _counter_tile(self, label: str, var: tk.StringVar,
                      color: str, parent: tk.Frame, col: int) -> None:
        tile = tk.Frame(parent, bg=PANEL, padx=22, pady=10)
        tile.grid(row=0, column=col, padx=10)
        tk.Label(tile, text=label, bg=PANEL, fg=FG_DIM,
                 font=("Courier New", 9)).pack()
        tk.Label(tile, textvariable=var, bg=PANEL, fg=color,
                 font=("Courier New", 30, "bold")).pack()

    # ------------------------------------------------------------------
    # Pipeline canvas
    # ------------------------------------------------------------------

    def _build_pipeline(self, parent: tk.Frame) -> None:
        """
        Draw the static pipeline and store canvas item IDs so individual
        stage boxes can be highlighted later via _highlight_stage().

        Layout mirrors anim.py:
          4 component lanes (barrel / tip / cartridge / cap)
            each: [MAKE] → [QC] → [BIN] ─┐
                                           ├→ [ASSEMBLY] → [FINAL QC] → [PACK] → [SHIP]
        """
        c = tk.Canvas(parent, bg=PANEL, width=_CW, height=_CH,
                      highlightthickness=0)
        c.pack(padx=10, pady=(0, 8))
        self._pipe_canvas = c

        abbr = {"barrel": "BAR", "tip": "TIP", "cartridge": "CART", "cap": "CAP"}

        def box(cx: int, cy: int, label: str, key: str) -> None:
            x0, y0 = cx - _BHW, cy - _BHH
            x1, y1 = cx + _BHW, cy + _BHH
            r = c.create_rectangle(x0, y0, x1, y1,
                                   fill=PANEL, outline=FG_DIM, width=1)
            t = c.create_text(cx, cy, text=label, fill=FG_DIM,
                              font=("Courier New", 7, "bold"), justify="center")
            self._stage_items[key] = (r, t)

        def arrow(x1: int, y1: int, x2: int, y2: int) -> None:
            c.create_line(x1, y1, x2, y2, fill=FG_DIM, width=1,
                          arrow=tk.LAST, arrowshape=(5, 7, 3))

        # Component lanes
        for name, y in _LANE_Y.items():
            s = abbr[name]
            box(_X_MAKE, y, f"MAKE\n{s}",   f"make_{name}")
            box(_X_QC,   y, f"QC\n{s}",     f"qc_{name}")
            box(_X_BIN,  y, f"BIN\n{s}",    f"bin_{name}")
            arrow(_X_MAKE + _BHW, y,          _X_QC  - _BHW, y)
            arrow(_X_QC  + _BHW, y,          _X_BIN - _BHW, y)
            # diagonal convergence from BIN → ASSEMBLY
            arrow(_X_BIN + _BHW, y,          _X_ASSM - _BHW, _CTR_Y)

        # Downstream stations (shared centre row)
        box(_X_ASSM, _CTR_Y, "ASSM",        "assembly")
        box(_X_FQC,  _CTR_Y, "FINAL\nQC",   "final_qc")
        box(_X_PACK, _CTR_Y, "PACK",        "packaging")
        box(_X_SHIP, _CTR_Y, "SHIP",        "shipped")

        arrow(_X_ASSM + _BHW, _CTR_Y,       _X_FQC  - _BHW, _CTR_Y)
        arrow(_X_FQC  + _BHW, _CTR_Y,       _X_PACK - _BHW, _CTR_Y)
        arrow(_X_PACK + _BHW, _CTR_Y,       _X_SHIP - _BHW, _CTR_Y)

    # ------------------------------------------------------------------
    # Stage highlighting
    # ------------------------------------------------------------------

    def _highlight_stage(self, stage: str, component: str) -> None:
        """Light up the active stage box in the component's colour."""
        if self._active_stage and self._active_stage in self._stage_items:
            r, t = self._stage_items[self._active_stage]
            self._pipe_canvas.itemconfig(r, fill=PANEL, outline=FG_DIM)
            self._pipe_canvas.itemconfig(t, fill=FG_DIM)

        self._active_stage = stage
        if stage not in self._stage_items:
            return
        color = COMP_COLORS.get(component, ACCENT)
        r, t = self._stage_items[stage]
        self._pipe_canvas.itemconfig(r, fill=color, outline=color)
        self._pipe_canvas.itemconfig(t, fill="#111111")

    def _reset_pipeline(self) -> None:
        for r, t in self._stage_items.values():
            self._pipe_canvas.itemconfig(r, fill=PANEL, outline=FG_DIM)
            self._pipe_canvas.itemconfig(t, fill=FG_DIM)
        self._active_stage = None

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def _start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._n_assembled = 0
        self._n_rejected  = 0
        self._assembled_var.set("0")
        self._rejected_var.set("0")
        self._tree.delete(*self._tree.get_children())
        self._status_var.set("● Running")
        self._reset_pipeline()

        self._stop_event.clear()
        random.seed(42)
        line = InstrumentedLine(self._q, self._stop_event)
        self._thread = threading.Thread(target=line.run_until_stopped, daemon=True)
        self._thread.start()

        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")

    def _stop(self) -> None:
        self._stop_event.set()
        self._btn_stop.config(state="disabled")

    # ------------------------------------------------------------------
    # Event pump  (UI thread, every 50 ms)
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        try:
            while True:
                evt = self._q.get_nowait()
                t = evt["type"]
                if t == EVT_ASSEMBLED:
                    self._n_assembled += 1
                    self._assembled_var.set(str(self._n_assembled))
                elif t == EVT_REJECTED:
                    self._n_rejected += 1
                    self._rejected_var.set(str(self._n_rejected))
                    self._tree.insert("", "end", values=(
                        evt["item"], evt["station"], evt["reason"],
                    ))
                    self._tree.yview_moveto(1.0)
                elif t == EVT_STAGE:
                    self._highlight_stage(evt["stage"], evt["component"])
                elif t == EVT_STATUS:
                    self._status_var.set(evt["msg"])
                elif t == EVT_STOPPED:
                    self._reset_pipeline()
                    self._btn_start.config(state="normal")
        except queue.Empty:
            pass
        self.after(50, self._poll)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    HMI().mainloop()
