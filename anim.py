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

# Pre-computed once: the docking point at the Assembly station.
# Used every frame by parts traveling diagonally toward it, so caching
# it here avoids re-doing the same arithmetic on every tick.
ASSEMBLY_TARGET_X = X_ASSEMBLY - 0.5
ASSEMBLY_TARGET_Y = PEN_Y

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
    """Drop a labeled rounded box on the canvas. Used only for the static
    background — these never move or get redrawn."""
    box = FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.04",
        facecolor=color, edgecolor="#333", linewidth=1.2, zorder=2,
    )
    ax.add_patch(box)
    ax.text(x, y, label, ha="center", va="center",
            fontsize=8.5, weight="bold", zorder=3)


# Component lanes — one row per component type, each with its own
# Maker → QC → Bin chain plus the diagonal feeder line into Assembly.
for ct in COMPONENT_TYPES:
    y = LANE_Y[ct]
    draw_station(X_MAKER, y, 1.3, 0.9, f"Make\n{ct}", "#fff3cd")
    draw_station(X_QC,    y, 1.0, 0.9, "QC",          "#cce5ff")
    draw_station(X_BIN,   y, 1.0, 0.9, "Bin",         "#fffacd")
    ax.plot([X_MAKER + 0.65, X_BIN - 0.5], [y, y],
            color="#bbb", linewidth=1, zorder=1)
    ax.plot([X_BIN + 0.5, X_ASSEMBLY - 0.9], [y, PEN_Y],
            color="#bbb", linewidth=1, zorder=1)

# Downstream — single shared row from Assembly through to the Shipped tray.
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

# Live text overlays — these stay around the whole animation and just
# get their text updated each frame.
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
    """Walk every component one tick along whatever path it's on.

    Each component carries a 'stage' string that says where it is in its
    journey. We branch on that and either nudge it closer to its next
    waypoint, or — if it's arrived — flag it for removal so the caller
    can drop it from the items list.
    """
    global arrivals_at_assembly
    for it in items:
        if it["kind"] != "component":
            continue
        stage = it["stage"]

        if stage == "to_qc":
            # Rolling right toward the QC station. When it gets there,
            # decide whether it survives inspection or falls off the belt.
            it["x"] += SPEED
            if it["x"] >= X_QC:
                it["stage"] = "falling" if it["defective"] else "to_bin"

        elif stage == "to_bin":
            # Past QC, heading into its bin. On arrival we just bump the
            # bin counter and retire the moving circle.
            it["x"] += SPEED
            if it["x"] >= X_BIN:
                bins[it["type"]] += 1
                to_remove.append(it)

        elif stage == "falling":
            # Defective part dropping off the belt — animated downward
            # until it's clearly off-screen, then counted as a reject.
            it["y"] -= SPEED * 1.4
            if it["y"] < -0.5:
                counters["rejected"] += 1
                to_remove.append(it)

        elif stage == "to_assembly":
            # Diagonal travel from a bin to the Assembly docking point.
            # We compute a unit vector toward the target and step along it;
            # once we're within one step's distance, count it as arrived.
            dx = ASSEMBLY_TARGET_X - it["x"]
            dy = ASSEMBLY_TARGET_Y - it["y"]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < SPEED:
                arrivals_at_assembly += 1
                to_remove.append(it)
            else:
                it["x"] += SPEED * dx / dist
                it["y"] += SPEED * dy / dist


def step_pens(to_remove):
    """Push assembled pens through the final stages: QC → Pack → Ship.

    Pens always travel left-to-right along the centre line, so the logic
    is much simpler than for components. The next_stage table says where
    each stage hands off to and at what x-coordinate the handoff happens.
    """
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
            # Reached the next station. Three possible outcomes:
            if stage == "to_final_qc" and it.get("defective"):
                # Failed final QC — yank it off the line.
                counters["rejected"] += 1
                to_remove.append(it)
            elif nxt == "done":
                # Made it all the way: park a permanent dot in the
                # Shipped tray, laid out in a 4-column grid.
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
                # Otherwise it's just moving on to the next stage.
                it["stage"] = nxt


def maybe_spawn_components():
    """Roll the dice for each maker. If its timer's up, emit a new part
    (which might be defective) and reset the timer to a random delay.
    The randomness keeps the four lanes from firing in sync, which would
    look mechanical."""
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
    """Whenever every bin has at least one part queued and nothing's
    currently in flight to Assembly, pull one of each from the bins and
    send them on the diagonal. The frame % 12 check just paces the
    dispatches so they don't all go off back-to-back."""
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
    """Once four components have arrived at Assembly, consume them and
    spawn a fresh pen heading toward Final QC. The 2% defect chance here
    is the assembly process itself failing (separate from component
    defects, which are caught earlier)."""
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
    """Draw a fresh circle for every moving thing and every part stacked
    in a bin. These all get wiped at the start of the next frame — only
    the static background and the shipped tray persist between frames."""
    for it in items:
        radius = 0.22 if it["kind"] == "pen" else 0.17
        c = Circle((it["x"], it["y"]), radius,
                   facecolor=COLORS[it["type"]],
                   edgecolor="#222", linewidth=1, zorder=5)
        ax.add_patch(c)
        frame_artists.append(c)

    # Show bin contents as small stacked dots, capped at 4 visible per bin
    # (the actual bin counter can go higher; this is just a visual hint).
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
    """One animation tick — called by FuncAnimation TOTAL_FRAMES times.

    The order matters: spawn first so new parts can move this frame,
    then step everything, then prune what's done, then dispatch any
    new assembly batch, then check for finished pens, then redraw.
    """
    # Wipe last frame's transient circles. Only the moving items and
    # bin-stack dots are cleared; static background and shipped pens stay.
    for a in frame_artists:
        a.remove()
    frame_artists.clear()

    maybe_spawn_components()

    to_remove: list = []
    step_components(to_remove)
    step_pens(to_remove)

    # Drop everything that finished its journey this frame.
    # Using a set of object ids to filter is O(n) total, vs the previous
    # O(n²) approach that did `items.remove(it)` for each retiree.
    if to_remove:
        retired_ids = {id(it) for it in to_remove}
        items[:] = [it for it in items if id(it) not in retired_ids]

    maybe_dispatch_assembly(frame)
    maybe_emit_pen()
    render_dynamic()

    # Refresh the bottom counter line.
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