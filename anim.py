"""
ballpen_animation.py
====================
A visual companion to ballpen_production_line.py.

Shows the line as an animated conveyor:
  - Components are spawned at "Maker" stations and roll right.
  - At QC, defective parts fall off the belt; good ones land in their bin.
  - When all four bins have at least one part, four components travel
    diagonally into the Assembly station.
  - A finished pen leaves Assembly and rides through Final QC and
    Packaging into the Shipped tray.
  - Live counters at the bottom track makes / rejects / shipped.

Run:
    python ballpen_animation.py
The script writes ballpen_production_line.gif next to itself.
"""

import random
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.patches import Circle, FancyBboxPatch
import matplotlib.pyplot as plt

random.seed(42)

# ---------------------------------------------------------------------------
# Layout constants - one source of truth for where every station lives.
# ---------------------------------------------------------------------------
COMPONENT_TYPES = ["barrel", "tip", "cartridge", "cap"]
COLORS = {
    "barrel":    "#3498db",
    "tip":       "#9b59b6",
    "cartridge": "#2ecc71",
    "cap":       "#e74c3c",
    "pen":       "#f39c12",
}

X_MAKER, X_QC, X_BIN          = 1.5, 3.5, 5.5
X_ASSEMBLY, X_FINAL_QC        = 8.0, 10.0
X_PACKAGING, X_SHIPPED        = 12.0, 14.0
LANE_Y = {"barrel": 8, "tip": 6, "cartridge": 4, "cap": 2}
PEN_Y  = 5.0
SPEED  = 0.13           # x units per frame
TOTAL_FRAMES = 260

# ---------------------------------------------------------------------------
# Figure setup - everything drawn here is static background.
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(12, 5.5), dpi=80)
ax.set_xlim(0, 15.5)
ax.set_ylim(-1, 10)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("#f7f9fc")

ax.text(7.75, 9.5, "Ball Pen Production Line",
        ha="center", fontsize=18, weight="bold", color="#222")


def draw_station(x, y, w, h, label, color):
    box = FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.04",
        facecolor=color, edgecolor="#333", linewidth=1.2, zorder=2,
    )
    ax.add_patch(box)
    ax.text(x, y, label, ha="center", va="center",
            fontsize=8.5, weight="bold", zorder=3)


# Component lanes
for ct in COMPONENT_TYPES:
    y = LANE_Y[ct]
    draw_station(X_MAKER, y, 1.3, 0.9, f"Make\n{ct}", "#fff3cd")
    draw_station(X_QC,    y, 1.0, 0.9, "QC",          "#cce5ff")
    draw_station(X_BIN,   y, 1.0, 0.9, "Bin",         "#fffacd")
    ax.plot([X_MAKER + 0.65, X_BIN - 0.5], [y, y],
            color="#bbb", linewidth=1, zorder=1)
    ax.plot([X_BIN + 0.5, X_ASSEMBLY - 0.9], [y, PEN_Y],
            color="#bbb", linewidth=1, zorder=1)

# Downstream
draw_station(X_ASSEMBLY,   PEN_Y, 1.8, 5.0, "Assembly", "#ffe4e1")
draw_station(X_FINAL_QC,   PEN_Y, 1.2, 0.9, "Final\nQC", "#cce5ff")
draw_station(X_PACKAGING,  PEN_Y, 1.2, 0.9, "Pack",     "#d4edda")
draw_station(X_SHIPPED,    PEN_Y, 1.5, 6.0, "Shipped",  "#e8f5e9")

ax.plot([X_ASSEMBLY + 0.9, X_FINAL_QC - 0.6], [PEN_Y, PEN_Y],
        color="#bbb", linewidth=1, zorder=1)
ax.plot([X_FINAL_QC + 0.6, X_PACKAGING - 0.6], [PEN_Y, PEN_Y],
        color="#bbb", linewidth=1, zorder=1)
ax.plot([X_PACKAGING + 0.6, X_SHIPPED - 0.75], [PEN_Y, PEN_Y],
        color="#bbb", linewidth=1, zorder=1)

# Live text overlays
counter_text = ax.text(7.75, -0.55, "", ha="center", fontsize=11, weight="bold")
bin_labels   = {ct: ax.text(X_BIN, LANE_Y[ct] - 0.6, "",
                            ha="center", fontsize=8, weight="bold")
                for ct in COMPONENT_TYPES}

# ---------------------------------------------------------------------------
# Simulation state - mutated each frame.
# ---------------------------------------------------------------------------
items: list[dict] = []                            # things currently moving
bins  = {ct: 0 for ct in COMPONENT_TYPES}         # parts queued for assembly
spawn_timers = {ct: random.randint(0, 15) for ct in COMPONENT_TYPES}
arrivals_at_assembly = 0
counters = {
    "made":     {ct: 0 for ct in COMPONENT_TYPES},
    "rejected": 0,
    "shipped":  0,
}

# Per-frame artists (cleared each tick)
frame_artists: list = []
shipped_dots: list  = []


def step_components(to_remove):
    """Move every component one tick along its path."""
    global arrivals_at_assembly
    for it in items:
        if it["kind"] != "component":
            continue
        stage = it["stage"]
        if stage == "to_qc":
            it["x"] += SPEED
            if it["x"] >= X_QC:
                it["stage"] = "falling" if it["defective"] else "to_bin"
        elif stage == "to_bin":
            it["x"] += SPEED
            if it["x"] >= X_BIN:
                bins[it["type"]] += 1
                to_remove.append(it)
        elif stage == "falling":
            it["y"] -= SPEED * 1.4
            if it["y"] < -0.5:
                counters["rejected"] += 1
                to_remove.append(it)
        elif stage == "to_assembly":
            tx, ty = X_ASSEMBLY - 0.5, PEN_Y
            dx, dy = tx - it["x"], ty - it["y"]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < SPEED:
                arrivals_at_assembly += 1
                to_remove.append(it)
            else:
                it["x"] += SPEED * dx / dist
                it["y"] += SPEED * dy / dist


def step_pens(to_remove):
    """Advance assembled pens through final QC, packaging, and shipping."""
    next_stage = {
        "to_final_qc":  ("to_packaging", X_FINAL_QC),
        "to_packaging": ("to_shipped",   X_PACKAGING),
        "to_shipped":   ("done",         X_SHIPPED),
    }
    for it in items:
        if it["kind"] != "pen":
            continue
        stage = it["stage"]
        nxt, target = next_stage[stage]
        it["x"] += SPEED
        if it["x"] >= target:
            if stage == "to_final_qc" and it.get("defective"):
                counters["rejected"] += 1
                to_remove.append(it)
            elif nxt == "done":
                counters["shipped"] += 1
                idx = counters["shipped"] - 1
                col, row = idx % 4, idx // 4
                sx = X_SHIPPED - 0.55 + col * 0.32
                sy = PEN_Y - 2 + row * 0.45
                dot = Circle((sx, sy), 0.12,
                             facecolor=COLORS["pen"], edgecolor="#333", zorder=4)
                ax.add_patch(dot)
                shipped_dots.append(dot)
                to_remove.append(it)
            else:
                it["stage"] = nxt


def maybe_spawn_components():
    """Each maker emits a part on its own random schedule."""
    for ct in COMPONENT_TYPES:
        spawn_timers[ct] -= 1
        if spawn_timers[ct] <= 0:
            counters["made"][ct] += 1
            items.append({
                "type": ct, "kind": "component",
                "x": X_MAKER, "y": LANE_Y[ct],
                "defective": random.random() < 0.05,
                "stage": "to_qc",
            })
            spawn_timers[ct] = random.randint(22, 38)


def maybe_dispatch_assembly(frame):
    """If every bin has stock, send one of each toward Assembly."""
    in_flight = sum(1 for i in items
                    if i["kind"] == "component" and i["stage"] == "to_assembly")
    ready = all(bins[ct] >= 1 for ct in COMPONENT_TYPES)
    if in_flight == 0 and ready and frame % 12 == 0:
        for ct in COMPONENT_TYPES:
            bins[ct] -= 1
            items.append({
                "type": ct, "kind": "component",
                "x": X_BIN, "y": LANE_Y[ct],
                "defective": False,
                "stage": "to_assembly",
            })


def maybe_emit_pen():
    """When 4 components have docked at Assembly, spit out a pen."""
    global arrivals_at_assembly
    if arrivals_at_assembly >= 4:
        arrivals_at_assembly -= 4
        items.append({
            "type": "pen", "kind": "pen",
            "x": X_ASSEMBLY + 0.5, "y": PEN_Y,
            "defective": random.random() < 0.02,
            "stage": "to_final_qc",
        })


def render_dynamic():
    """Draw circles for everything currently in motion + bin stacks."""
    for it in items:
        radius = 0.22 if it["kind"] == "pen" else 0.17
        c = Circle((it["x"], it["y"]), radius,
                   facecolor=COLORS[it["type"]],
                   edgecolor="#222", linewidth=1, zorder=5)
        ax.add_patch(c)
        frame_artists.append(c)

    for ct in COMPONENT_TYPES:
        for i in range(min(bins[ct], 4)):
            cx = X_BIN - 0.25 + (i % 2) * 0.25
            cy = LANE_Y[ct] - 0.2 + (i // 2) * 0.25
            d = Circle((cx, cy), 0.09,
                       facecolor=COLORS[ct], edgecolor="#333", zorder=3)
            ax.add_patch(d)
            frame_artists.append(d)
        bin_labels[ct].set_text(f"x{bins[ct]}" if bins[ct] else "")


def update(frame):
    """One animation tick."""
    for a in frame_artists:
        a.remove()
    frame_artists.clear()

    maybe_spawn_components()
    to_remove: list = []
    step_components(to_remove)
    step_pens(to_remove)
    for it in to_remove:
        if it in items:
            items.remove(it)

    maybe_dispatch_assembly(frame)
    maybe_emit_pen()
    render_dynamic()

    m = counters["made"]
    counter_text.set_text(
        f"Made:  barrels {m['barrel']}   tips {m['tip']}   "
        f"cartridges {m['cartridge']}   caps {m['cap']}        "
        f"Rejected: {counters['rejected']}        Shipped: {counters['shipped']}"
    )
    return [counter_text] + list(bin_labels.values()) + frame_artists + shipped_dots


# ---------------------------------------------------------------------------
# Build the animation and save as GIF.
# ---------------------------------------------------------------------------
ani = FuncAnimation(fig, update, frames=TOTAL_FRAMES, interval=50, blit=False)

if __name__ == "__main__":
    out = "ballpen_production_line.gif"
    ani.save(out, writer=PillowWriter(fps=20))
    print(f"Saved animation to {out}")