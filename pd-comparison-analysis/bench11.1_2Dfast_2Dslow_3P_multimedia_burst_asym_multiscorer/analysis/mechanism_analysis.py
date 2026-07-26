"""bench11.1: test whether deferred-decode is the mechanism behind coord's
tail-latency win at bursts 64 and 128.

Parses each decode pod's vLLM modelserver.log for `loggers.py:271`
snapshots (Running/Waiting/KV%), filters to the burst-64 and burst-128
windows, and produces:

  - pod_running_burst64.png   (per-pod Running-reqs timeline)
  - pod_running_burst128.png
  - pod_saturation_bar.png    (mean Running/max_seqs per pod x side x burst)
  - queue_depth.png           (sum Waiting across the 4 pods vs time)

Plus prints an interpretation-friendly summary table.

Runs standalone: `python3 mechanism_analysis.py`.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

BASE = Path(
    "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/"
    "pd-comparison-analysis/"
    "bench11.1_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer"
)

# All timestamps in the pod logs are UTC (naked "07-26 HH:MM:SS"); the
# bench-log timestamps are also UTC — see sglang_bench.log's `[Sun Jul 26
# 08:34:21 AM UTC 2026]` headers.
def utc(t):
    return datetime(2026, 7, 26, *t, tzinfo=timezone.utc).timestamp()

WINDOWS = {
    "coord": {
        64:  (utc((8, 40, 34)), utc((8, 44,  4))),
        128: (utc((8, 44,  4)), utc((8, 49, 47))),
    },
    "sidecar": {
        64:  (utc((9, 30, 30)), utc((9, 33, 59))),
        128: (utc((9, 33, 59)), utc((9, 40,  2))),
    },
}

PODS = {
    "coord": {
        "fast_A": ("epd-nvidia-gpu-vllm-decode-d9d499948-4fb9l",      8),
        "fast_B": ("epd-nvidia-gpu-vllm-decode-d9d499948-ccdx2",      8),
        "slow_A": ("epd-nvidia-gpu-vllm-decode-slow-7b7f4bb875-5zmjg", 4),
        "slow_B": ("epd-nvidia-gpu-vllm-decode-slow-7b7f4bb875-6lk9k", 4),
    },
    "sidecar": {
        "fast_A": ("pd-disaggregation-nvidia-gpu-vllm-decode-85bf598f64-kqv2n",       8),
        "fast_B": ("pd-disaggregation-nvidia-gpu-vllm-decode-85bf598f64-v5xlx",       8),
        "slow_A": ("pd-disaggregation-nvidia-gpu-vllm-decode-slow-fb857c8f5-dl4cg",   4),
        "slow_B": ("pd-disaggregation-nvidia-gpu-vllm-decode-slow-fb857c8f5-srdjk",   4),
    },
}

LOG_SUBDIR = {
    "coord":   "coord/pod_logs_dpikus-epd-sglang-bench_20260726_120117",
    "sidecar": "sidecar/pod_logs_dpikus-pd-sglang-bench_20260726_125241",
}

LINE_RE = re.compile(
    r"INFO (\d\d)-(\d\d) (\d\d):(\d\d):(\d\d) \[loggers\.py:271\].*?"
    r"Running: (\d+) reqs, Waiting: (\d+) reqs(?:, Deferred: (\d+) reqs)?.*?"
    r"GPU KV cache usage: ([\d.]+)%"
)


def parse_pod_log(path):
    """Return a list of (utc_seconds, running, waiting, kv_pct) tuples."""
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


# Build data: series[side][burst][pod_key] = list of (t_offset_s, running, waiting, kv)
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

# Sanity-check summary
print(f"\n{'side':<8} {'burst':>5} {'pod':<7} {'snaps':>5} {'peak_R':>6} {'peak_W':>6}")
for side in ("coord", "sidecar"):
    for burst in (64, 128):
        for pod_key in ("fast_A", "fast_B", "slow_A", "slow_B"):
            data = series[side][burst][pod_key]
            n = len(data)
            peakR = max((r for _, r, _, _ in data), default=0)
            peakW = max((w for _, _, w, _ in data), default=0)
            print(f"{side:<8} {burst:>5} {pod_key:<7} {n:>5} {peakR:>6} {peakW:>6}")

# ------------------------------------------------------------------
# Metrics
# ------------------------------------------------------------------
def mean_saturation(pod_series, max_seqs):
    if not pod_series:
        return 0.0
    return sum(r for _, r, _, _ in pod_series) / (len(pod_series) * max_seqs)


def imbalance(all_pod_series, max_seqs_by_pod):
    """Mean over snapshots of stdev(Running_i / max_seqs_i) across pods.

    Aligns snapshots by nearest-timestamp bucket (10-second-ish grid).
    """
    # Build union of timestamps rounded to 5s bucket
    all_t = sorted({round(t / 5) * 5
                    for k in all_pod_series for t, *_ in all_pod_series[k]})
    if not all_t:
        return 0.0
    diffs = []
    for tb in all_t:
        vals = []
        for k, s in all_pod_series.items():
            near = [r for t, r, *_ in s if abs(round(t / 5) * 5 - tb) < 3]
            if near:
                vals.append(near[0] / max_seqs_by_pod[k])
        if len(vals) >= 2:
            diffs.append(np.std(vals))
    return float(np.mean(diffs)) if diffs else 0.0


def waiting_integral(all_pod_series):
    """trapezoid-integrated sum-of-waiting across the 4 pods (req-seconds)."""
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


print("\n\n" + "=" * 78)
print("Per-pod metrics over the burst window")
print("=" * 78)
print(f"{'side':<8} {'burst':>5} {'pod':<7} {'max':>4} {'mean_R':>7} {'sat':>6} {'peakR':>6} {'peakW':>6}")
for side in ("coord", "sidecar"):
    for burst in (64, 128):
        for pod_key in ("fast_A", "fast_B", "slow_A", "slow_B"):
            _, max_seqs = PODS[side][pod_key]
            data = series[side][burst][pod_key]
            if not data:
                continue
            mean_r = sum(r for _, r, _, _ in data) / len(data)
            sat = mean_saturation(data, max_seqs)
            peakR = max(r for _, r, _, _ in data)
            peakW = max(w for _, _, w, _ in data)
            print(f"{side:<8} {burst:>5} {pod_key:<7} {max_seqs:>4} "
                  f"{mean_r:>7.2f} {sat:>6.2f} {peakR:>6} {peakW:>6}")

print("\n" + "=" * 78)
print("Fleet-level metrics per burst")
print("=" * 78)
print(f"{'side':<8} {'burst':>5} {'imbal':>7} {'waitint':>10} "
      f"{'fast_sat':>9} {'slow_sat':>9}")
verdict = {}
for side in ("coord", "sidecar"):
    for burst in (64, 128):
        max_by_pod = {k: PODS[side][k][1] for k in PODS[side]}
        imb = imbalance(series[side][burst], max_by_pod)
        wi = waiting_integral(series[side][burst])
        fast_sat = np.mean([
            mean_saturation(series[side][burst][k], 8)
            for k in ("fast_A", "fast_B")
            if series[side][burst][k]
        ])
        slow_sat = np.mean([
            mean_saturation(series[side][burst][k], 4)
            for k in ("slow_A", "slow_B")
            if series[side][burst][k]
        ])
        verdict[(side, burst)] = dict(imbal=imb, waitint=wi,
                                      fast_sat=fast_sat, slow_sat=slow_sat)
        print(f"{side:<8} {burst:>5} {imb:>7.4f} {wi:>10.1f} "
              f"{fast_sat:>9.2f} {slow_sat:>9.2f}")

# ------------------------------------------------------------------
# Charts
# ------------------------------------------------------------------
FAST_COLOR = "#2b6cb0"
SLOW_COLOR = "#c05621"

def plot_running(burst, fname):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, side in zip(axes, ("coord", "sidecar")):
        for pod_key, ls in (("fast_A", "-"), ("fast_B", "--"),
                            ("slow_A", "-"), ("slow_B", "--")):
            data = series[side][burst][pod_key]
            if not data:
                continue
            xs = [t for t, *_ in data]
            ys = [r for _, r, _, _ in data]
            color = FAST_COLOR if pod_key.startswith("fast") else SLOW_COLOR
            _, max_seqs = PODS[side][pod_key]
            label = f"{pod_key} (max={max_seqs})"
            ax.plot(xs, ys, color=color, linestyle=ls, marker="o",
                    markersize=4, label=label)
        ax.axhline(8, color=FAST_COLOR, linestyle=":", alpha=0.4,
                   linewidth=1, label="fast cap (8)")
        ax.axhline(4, color=SLOW_COLOR, linestyle=":", alpha=0.4,
                   linewidth=1, label="slow cap (4)")
        ax.set_xlabel("seconds since burst start")
        ax.set_ylabel("Running reqs")
        ax.set_title(f"{side} — burst {burst}")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc="upper right")
    fig.suptitle(f"Per-decode-pod concurrent Running requests over the burst "
                 f"{burst} window")
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / fname, dpi=130)
    plt.close(fig)


def plot_saturation():
    fig, ax = plt.subplots(figsize=(10, 4.5))
    positions = np.arange(4)
    width = 0.2
    groups = [("coord", 64),   ("sidecar", 64),
              ("coord", 128),  ("sidecar", 128)]
    labels = ["coord b64", "sidecar b64", "coord b128", "sidecar b128"]
    colors = ["#2b6cb0", "#c05621", "#2c5282", "#9c4221"]
    pod_order = ("fast_A", "fast_B", "slow_A", "slow_B")
    for i, ((side, burst), lbl, col) in enumerate(zip(groups, labels, colors)):
        vals = []
        for k in pod_order:
            _, mx = PODS[side][k]
            vals.append(mean_saturation(series[side][burst][k], mx))
        ax.bar(positions + i * width, vals, width, color=col, label=lbl)
    ax.set_xticks(positions + 1.5 * width)
    ax.set_xticklabels([f"{k}\n(max={PODS['coord'][k][1]})" for k in pod_order])
    ax.set_ylabel("mean saturation (Running / max_seqs)")
    ax.set_ylim(0, 1.05)
    ax.axhline(1.0, color="k", linewidth=0.5, alpha=0.3)
    ax.set_title("Per-pod mean saturation over the burst window\n"
                 "(sidecar > coord on slow pods ⇒ deferred-decode mechanism supported)")
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / "pod_saturation_bar.png", dpi=130)
    plt.close(fig)


def plot_queue_depth():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, burst in zip(axes, (64, 128)):
        for side, color in (("coord", "#2b6cb0"), ("sidecar", "#c05621")):
            # sum Waiting across pods at each timestamp, aligned to 5s buckets
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
    fig.suptitle("Fleet-wide queued-request depth over each burst window")
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / "queue_depth.png", dpi=130)
    plt.close(fig)


plot_running(64, "pod_running_burst64.png")
plot_running(128, "pod_running_burst128.png")
plot_saturation()
plot_queue_depth()

print("\nSaved:")
for f in ("pod_running_burst64.png", "pod_running_burst128.png",
          "pod_saturation_bar.png", "queue_depth.png"):
    print(f"  analysis/{f}")
