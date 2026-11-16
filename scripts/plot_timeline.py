"""Draws a per-agent heartbeat timeline from an audit log.

    python scripts/plot_timeline.py [audit_log] [output.png]

Defaults to docs/sample-run.log and docs/timeline.png. Each row is one agent:
ticks are heartbeats, the shaded span is time the monitor considered the agent
down, and the label gives detection time (silence before the DOWN alert, as the monitor measured it).
"""

import re
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
LINE = re.compile(r"^(\S+) \[(\w+)\] (.*)$")

INK = "#1b2a3a"
MUTED = "#6b7a89"
ALIVE = "#1f8a70"
DOWN = "#c8402e"


def parse(path):
    """Returns per-agent heartbeat times, DOWN alerts, recoveries, and the run's start and end."""
    beats, downs, recoveries = {}, [], []
    first = last = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        ts = datetime.fromisoformat(m.group(1))
        first = first or ts
        last = ts
        msg = m.group(3)
        if hb := re.match(r"Heartbeat from (\S+)", msg):
            beats.setdefault(hb.group(1), []).append(ts)
        elif dn := re.match(r"Agent (\S+) DOWN \(no heartbeat for ([\d.]+)s\)", msg):
            downs.append((dn.group(1), ts, float(dn.group(2))))
        elif rc := re.match(r"Agent (\S+) registered", msg):
            recoveries.append((rc.group(1), ts))
    return beats, downs, recoveries, first, last


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs" / "sample-run.log"
    out = sys.argv[2] if len(sys.argv) > 2 else ROOT / "docs" / "timeline.png"
    beats, downs, recoveries, t0, t_end = parse(src)
    sec = lambda t: (t - t0).total_seconds()
    agents = sorted(beats)

    fig, ax = plt.subplots(figsize=(10, 3.4))
    latencies = []
    for row, agent in enumerate(agents):
        y = len(agents) - 1 - row
        times = [sec(t) for t in beats[agent]]
        ax.vlines(times, y - 0.28, y + 0.28, color=ALIVE, linewidth=2)
        for who, t_down, idle in downs:
            if who != agent:
                continue
            last_hb = max(t for t in beats[agent] if t <= t_down)
            back = [t for w, t in recoveries if w == agent and t > t_down]
            end = sec(back[0]) if back else sec(t_end)
            ax.fill_between([sec(last_hb), end], y - 0.32, y + 0.32, color=DOWN, alpha=0.14, linewidth=0)
            ax.plot(sec(t_down), y, marker="v", color=DOWN, markersize=9, zorder=3)
            latency = idle  # the monitor's own measurement, finer than the 1 s log timestamps
            latencies.append(latency)
            ax.annotate(f"flagged {latency:.1f} s after last heartbeat", (sec(t_down), y + 0.34),
                        ha="left", va="bottom", fontsize=9, color=DOWN, xytext=(6, 0), textcoords="offset points")

    ax.set_yticks(range(len(agents)), list(reversed(agents)), fontsize=11, color=INK)
    ax.set_ylim(-0.7, len(agents) - 0.2)
    ax.set_xlim(0, sec(t_end) + 2)
    ax.set_xlabel("Seconds since the monitor started", fontsize=10, color=MUTED)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c9d1d9")
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", colors=MUTED)
    worst = max(latencies) if latencies else 0
    ax.set_title(f"Every failure was flagged within {worst:.1f} seconds of an agent's last heartbeat",
                 fontsize=13, fontweight="bold", color=INK, loc="left", pad=14)
    plt.tight_layout()
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
