"""2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_trace: same per-pod concurrency mechanism analysis as 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed,
run against 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_trace's modelserver.logs to test reproducibility of the
tail-drain signal.

This is our fallback because the EPP V(4) approach didn't yield per-request
target-pod attribution (dev-fork EPP images don't emit the picker trace
lines, and sidecar EPP log was truncated by container log rotation).

Outputs the same 4 PNGs as 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed's mechanism_analysis.py.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

BASE = Path(
    "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/"
    "pd-comparison-analysis/"
    "2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_trace"
)


def utc(t):
    return datetime(2026, 7, 26, *t, tzinfo=timezone.utc).timestamp()

WINDOWS = {
    "coord": {
        64:  (utc((12, 31, 26)), utc((12, 34, 52))),
        128: (utc((12, 34, 52)), utc((12, 40, 26))),
    },
    "sidecar": {
        64:  (utc((13, 23, 37)), utc((13, 27,  7))),
        128: (utc((13, 27,  7)), utc((13, 32, 49))),
    },
}

PODS = {
    "coord": {
        "fast_A": ("epd-nvidia-gpu-vllm-decode-d9d499948-75lvr",       8),
        "fast_B": ("epd-nvidia-gpu-vllm-decode-d9d499948-dj5sp",       8),
        "slow_A": ("epd-nvidia-gpu-vllm-decode-slow-7b7f4bb875-f9tkr", 4),
        "slow_B": ("epd-nvidia-gpu-vllm-decode-slow-7b7f4bb875-h4w6t", 4),
    },
    "sidecar": {
        "fast_A": ("pd-disaggregation-nvidia-gpu-vllm-decode-85bf598f64-hgnwf",       8),
        "fast_B": ("pd-disaggregation-nvidia-gpu-vllm-decode-85bf598f64-qj6qh",       8),
        "slow_A": ("pd-disaggregation-nvidia-gpu-vllm-decode-slow-fb857c8f5-wvh8r",   4),
        "slow_B": ("pd-disaggregation-nvidia-gpu-vllm-decode-slow-fb857c8f5-xl2ww",   4),
    },
}

LOG_SUBDIR = {
    "coord":   "coord/pod_logs_dpikus-epd-sglang-bench_20260726_155547",
    "sidecar": "sidecar/pod_logs_dpikus-pd-sglang-bench_20260726_164434",
}

LINE_RE = re.compile(
    r"INFO (\d\d)-(\d\d) (\d\d):(\d\d):(\d\d) \[loggers\.py:271\].*?"
    r"Running: (\d+) reqs, Waiting: (\d+) reqs(?:, Deferred: (\d+) reqs)?.*?"
    r"GPU KV cache usage: ([\d.]+)%"
)


def parse_pod_log(path):
    out = []
    with open(path) as f:
        for line in f:
            m = LINE_RE.search(line)
            if not m:
                continue
            month, day, hh, mm, ss = (int(x) for x in m.groups()[:5])
            running = int(m.group(6))
            waiting = int(m.group(7))
            kv = float(m.group(9))
            t = datetime(2026, month, day, hh, mm, ss,
                         tzinfo=timezone.utc).timestamp()
            out.append((t, running, waiting, kv))
    return out


series = {"coord": {64: {}, 128: {}}, "sidecar": {64: {}, 128: {}}}
for side in ("coord", "sidecar"):
    subdir = LOG_SUBDIR[side]
    for burst in (64, 128):
        t0, t1 = WINDOWS[side][burst]
        for pod_key, (pod_name, _max) in PODS[side].items():
            path = BASE / subdir / pod_name / "modelserver.log"
            snapshots = parse_pod_log(path)
            filtered = [
                (t - t0, r, w, kv) for (t, r, w, kv) in snapshots
                if t0 <= t <= t1
            ]
            series[side][burst][pod_key] = filtered

print(f"{'side':<8} {'burst':>5} {'pod':<7} {'snaps':>5} {'peakR':>5} {'peakW':>5}")
for side in ("coord", "sidecar"):
    for burst in (64, 128):
        for pod_key in ("fast_A", "fast_B", "slow_A", "slow_B"):
            data = series[side][burst][pod_key]
            peakR = max((r for _, r, _, _ in data), default=0)
            peakW = max((w for _, _, w, _ in data), default=0)
            print(f"{side:<8} {burst:>5} {pod_key:<7} {len(data):>5} {peakR:>5} {peakW:>5}")


def mean_saturation(pod_series, max_seqs):
    if not pod_series:
        return 0.0
    return sum(r for _, r, _, _ in pod_series) / (len(pod_series) * max_seqs)


def waiting_integral(all_pod_series):
    all_t = sorted({round(t / 5) * 5
                    for k in all_pod_series for t, *_ in all_pod_series[k]})
    if not all_t:
        return 0.0
    total = []
    for tb in all_t:
        s = 0
        for k, ser in all_pod_series.items():
            near = [w for t, _, w, _ in ser if abs(round(t / 5) * 5 - tb) < 3]
            s += near[0] if near else 0
        total.append(s)
    return float(np.trapezoid(total, all_t))


print("\n" + "=" * 74)
print("Per-pod mean saturation + fleet waiting-integral")
print("=" * 74)
print(f"{'side':<8} {'burst':>5} {'fast_A':>7} {'fast_B':>7} {'slow_A':>7} {'slow_B':>7} {'waitint':>10}")
for side in ("coord", "sidecar"):
    for burst in (64, 128):
        fs = [mean_saturation(series[side][burst][k], PODS[side][k][1])
              for k in ("fast_A", "fast_B", "slow_A", "slow_B")]
        wi = waiting_integral(series[side][burst])
        print(f"{side:<8} {burst:>5} {fs[0]:>7.2f} {fs[1]:>7.2f} {fs[2]:>7.2f} {fs[3]:>7.2f} {wi:>10.1f}")


FAST_COLOR = "#2b6cb0"
SLOW_COLOR = "#c05621"

def plot_running(burst, fname):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, side in zip(axes, ("coord", "sidecar")):
        for pod_key, ls in (("fast_A", "-"), ("fast_B", "--"),
                            ("slow_A", "-"), ("slow_B", "--")):
            data = series[side][burst][pod_key]
            if not data: continue
            xs = [t for t, *_ in data]
            ys = [r for _, r, _, _ in data]
            color = FAST_COLOR if pod_key.startswith("fast") else SLOW_COLOR
            _, max_seqs = PODS[side][pod_key]
            ax.plot(xs, ys, color=color, linestyle=ls, marker="o", markersize=4,
                    label=f"{pod_key} (max={max_seqs})")
        ax.axhline(8, color=FAST_COLOR, linestyle=":", alpha=0.4)
        ax.axhline(4, color=SLOW_COLOR, linestyle=":", alpha=0.4)
        ax.set_xlabel("seconds since burst start")
        ax.set_ylabel("Running reqs")
        ax.set_title(f"{side} — burst {burst}")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc="upper right")
    fig.suptitle(f"2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_trace — Per-decode-pod concurrent Running requests over burst {burst} window")
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / fname, dpi=130)
    plt.close(fig)


def plot_saturation():
    fig, ax = plt.subplots(figsize=(10, 4.5))
    positions = np.arange(4)
    width = 0.2
    groups = [("coord", 64),  ("sidecar", 64),
              ("coord", 128), ("sidecar", 128)]
    labels = ["coord b64", "sidecar b64", "coord b128", "sidecar b128"]
    colors = ["#2b6cb0", "#c05621", "#2c5282", "#9c4221"]
    pod_order = ("fast_A", "fast_B", "slow_A", "slow_B")
    for i, ((side, burst), lbl, col) in enumerate(zip(groups, labels, colors)):
        vals = [mean_saturation(series[side][burst][k], PODS[side][k][1])
                for k in pod_order]
        ax.bar(positions + i * width, vals, width, color=col, label=lbl)
    ax.set_xticks(positions + 1.5 * width)
    ax.set_xticklabels([f"{k}\n(max={PODS['coord'][k][1]})" for k in pod_order])
    ax.set_ylabel("mean saturation (Running / max_seqs)")
    ax.set_ylim(0, 1.05)
    ax.axhline(1.0, color="k", linewidth=0.5, alpha=0.3)
    ax.set_title("2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_trace — Per-pod mean saturation over the burst window")
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / "pod_saturation_bar.png", dpi=130)
    plt.close(fig)


def plot_queue_depth():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, burst in zip(axes, (64, 128)):
        for side, color in (("coord", "#2b6cb0"), ("sidecar", "#c05621")):
            grid_t = sorted({round(t / 5) * 5
                             for k in series[side][burst]
                             for t, *_ in series[side][burst][k]})
            totals = []
            for tb in grid_t:
                s = 0
                for k, ser in series[side][burst].items():
                    near = [w for t, _, w, _ in ser
                            if abs(round(t / 5) * 5 - tb) < 3]
                    s += near[0] if near else 0
                totals.append(s)
            ax.plot(grid_t, totals, color=color, marker="o", markersize=4,
                    label=side, linewidth=2)
        ax.set_xlabel("seconds since burst start")
        ax.set_ylabel("Σ Waiting reqs across 4 decode pods")
        ax.set_title(f"burst {burst}")
        ax.grid(True, alpha=0.3)
        ax.legend()
    fig.suptitle("2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_trace — Fleet-wide queued-request depth")
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / "queue_depth.png", dpi=130)
    plt.close(fig)


plot_running(64, "pod_running_burst64.png")
plot_running(128, "pod_running_burst128.png")
plot_saturation()
plot_queue_depth()
print("\nsaved 4 PNGs to analysis/")
