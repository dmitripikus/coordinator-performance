"""bench11.2 (re-run) — per-request routing analysis for the coord-vs-sidecar
deferred-decode mechanism question.

Parses each side's decode-EPP `epp.log` for `"Request handled"` entries and
attributes each request to fast_A / fast_B / slow_A / slow_B using the
IP -> pod-name -> variant map from the collected pod.yaml files.

Outputs:
  - fast_vs_slow_by_burst.png     bar: coord vs sidecar, per burst
  - routing_timeline_b64.png      cumulative per-pod-variant over the b64 window
  - routing_timeline_b128.png     same for b128
  - per_pod_assignments.png       full 4-way per-pod bar per side per burst
  - Prints a summary table and writes routing_summary.txt

Runs standalone: `python3 routing_analysis.py`.
"""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict

import matplotlib.pyplot as plt
import numpy as np

BASE = Path(
    "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/"
    "pd-comparison-analysis/"
    "bench11.2_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_routing_trace"
)


def find_epp_log_and_bench_log(side_dir):
    """Return (epp_log_path, bench_log_path, pod_logs_dir)."""
    pod_logs_dir = next(
        p for p in side_dir.iterdir()
        if p.is_dir() and p.name.startswith("pod_logs_")
    )
    epp_dirs = [d for d in pod_logs_dir.iterdir()
                if d.is_dir() and "-epp-" in d.name and "-prefill-" not in d.name
                and "-encode-" not in d.name]
    assert epp_dirs, f"no decode-epp dir found in {pod_logs_dir}"
    epp_log = epp_dirs[0] / "epp.log"
    bench_log = pod_logs_dir / "sglang_bench.log"
    return epp_log, bench_log, pod_logs_dir


def build_ip_map(pod_logs_dir):
    """Return {ip: {'name': str, 'variant': 'fast'|'slow'}} for all decode pods."""
    out = {}
    for pod_dir in pod_logs_dir.iterdir():
        if not pod_dir.is_dir():
            continue
        name = pod_dir.name
        # We want decode pods (fast and slow variants)
        if "-vllm-decode" not in name:
            continue
        # Skip prefill; both fast and slow decode pass this filter
        if "-prefill-" in name:
            continue
        pod_yaml = pod_dir / "pod.yaml"
        if not pod_yaml.exists():
            continue
        # Parse podIP from the YAML
        with open(pod_yaml) as f:
            content = f.read()
        m = re.search(r"^\s*podIP:\s*([\d.]+)\s*$", content, re.MULTILINE)
        if not m:
            continue
        ip = m.group(1)
        variant = "slow" if "-decode-slow-" in name else "fast"
        out[ip] = {"name": name, "variant": variant}
    return out


def parse_bench_windows(bench_log):
    """Return {burst_size: (t0_epoch, t1_epoch)}."""
    windows = {}
    starts = {}
    pat = re.compile(
        r"^\[.*? "
        r"(?P<hh>\d\d):(?P<mm>\d\d):(?P<ss>\d\d) [AP]M UTC "
        r"\d{4}\] "
        r"(?:=== burst_size (?P<burst_start>\d+) ===|"
        r"burst_size (?P<burst_end>\d+) done\.)"
    )
    # date is in the same line — extract it via a broader pattern
    header_pat = re.compile(
        r"^\[[A-Z][a-z]+ ([A-Z][a-z]+) (\d+) "
        r"(\d\d):(\d\d):(\d\d) ([AP])M UTC (\d{4})\] "
        r"(=== burst_size (\d+) ===|burst_size (\d+) done\.)"
    )
    months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
              "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    with open(bench_log) as f:
        seen_start = set()
        for line in f:
            m = header_pat.match(line)
            if not m:
                continue
            mon_str, day, hh, mm, ss, ap, yr, tag, bs_start, bs_end = m.groups()
            hh = int(hh); mm = int(mm); ss = int(ss)
            if ap == "P" and hh != 12:
                hh += 12
            if ap == "A" and hh == 12:
                hh = 0
            ts = datetime(int(yr), months[mon_str], int(day),
                          hh, mm, ss, tzinfo=timezone.utc).timestamp()
            if bs_start is not None:
                bsz = int(bs_start)
                if bsz not in seen_start:
                    starts[bsz] = ts
                    seen_start.add(bsz)
            elif bs_end is not None:
                bsz = int(bs_end)
                if bsz in starts:
                    windows[bsz] = (starts[bsz], ts)
    return windows


def parse_epp_routing(epp_log, ip_map):
    """Return list of {ts, request_id, ip, variant, pod_name}."""
    routes = []
    unknown_ips = Counter()
    with open(epp_log) as f:
        for line in f:
            # cheap prefilter
            if '"Request handled"' not in line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("msg") != "Request handled":
                continue
            ep = j.get("endpoint", "")
            ip = ep.split(":")[0] if ep else ""
            ts = j.get("ts", 0.0)
            rid = j.get("x-request-id", "")
            info = ip_map.get(ip)
            if info is None:
                unknown_ips[ip] += 1
                continue
            routes.append({
                "ts": ts, "rid": rid, "ip": ip,
                "variant": info["variant"], "name": info["name"],
            })
    if unknown_ips:
        print(f"  WARN: {sum(unknown_ips.values())} events had unmapped IPs: {dict(unknown_ips.most_common(5))}")
    return routes


def label_pod_key(ip_map):
    """Assign fast_A/fast_B/slow_A/slow_B ordering (by IP for determinism)."""
    ips_by_variant = defaultdict(list)
    for ip, info in ip_map.items():
        ips_by_variant[info["variant"]].append(ip)
    keys = {}
    for variant, letter_pairs in [("fast", ["fast_A", "fast_B"]),
                                   ("slow", ["slow_A", "slow_B"])]:
        for ip, key in zip(sorted(ips_by_variant[variant]), letter_pairs):
            keys[ip] = key
    return keys


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
sides = {}
for side in ("coord", "sidecar"):
    side_dir = BASE / side
    print(f"\n=== {side.upper()} ===")
    epp_log, bench_log, pod_logs_dir = find_epp_log_and_bench_log(side_dir)
    print(f"  epp_log:   {epp_log.name}")
    print(f"  bench_log: {bench_log.name}")
    ip_map = build_ip_map(pod_logs_dir)
    print(f"  ip_map: {ip_map}")
    windows = parse_bench_windows(bench_log)
    print(f"  windows: {windows}")
    pod_keys = label_pod_key(ip_map)
    print(f"  pod_keys: {pod_keys}")
    routes = parse_epp_routing(epp_log, ip_map)
    print(f"  parsed {len(routes)} routing decisions")
    sides[side] = {
        "epp_log": epp_log, "bench_log": bench_log,
        "pod_logs_dir": pod_logs_dir,
        "ip_map": ip_map, "pod_keys": pod_keys,
        "windows": windows, "routes": routes,
    }


# Per-side per-burst counts
BURSTS = [8, 16, 32, 64, 128, 256]
per_burst = {}  # side -> {burst -> {pod_key -> count}}
for side, s in sides.items():
    per_burst[side] = {}
    for burst in BURSTS:
        w = s["windows"].get(burst)
        c = Counter()
        if not w:
            per_burst[side][burst] = c
            continue
        t0, t1 = w
        for r in s["routes"]:
            if t0 <= r["ts"] <= t1:
                c[s["pod_keys"][r["ip"]]] += 1
        per_burst[side][burst] = c

# Print + write summary
lines_out = []
def emit(*args):
    line = " ".join(str(x) for x in args)
    print(line)
    lines_out.append(line)

emit()
emit("=" * 84)
emit("Per-request routing decisions per burst per side")
emit("=" * 84)
emit(f"{'side':<8} {'burst':>5} {'fast_A':>7} {'fast_B':>7} {'slow_A':>7} {'slow_B':>7} "
     f"{'fast%':>6} {'slow%':>6} {'total':>6}")
for side in ("coord", "sidecar"):
    for burst in BURSTS:
        c = per_burst[side][burst]
        fA = c.get("fast_A", 0); fB = c.get("fast_B", 0)
        sA = c.get("slow_A", 0); sB = c.get("slow_B", 0)
        tot = fA + fB + sA + sB
        fastpc = 100.0 * (fA + fB) / tot if tot else 0.0
        slowpc = 100.0 * (sA + sB) / tot if tot else 0.0
        emit(f"{side:<8} {burst:>5} {fA:>7} {fB:>7} {sA:>7} {sB:>7} "
             f"{fastpc:>5.1f}% {slowpc:>5.1f}% {tot:>6}")

# Additional: fleet fast/slow capacity ratio for reference
emit()
emit("Fleet capacity ratio (if load were proportional to max_num_seqs):")
emit("  fast: 8 seqs * 2 pods = 16 slots (66.7% of 24)")
emit("  slow: 4 seqs * 2 pods =  8 slots (33.3% of 24)")
emit("A no-op scheduler routing purely uniform-by-pod-count -> 50% fast, 50% slow")
emit("A capacity-proportional scheduler -> 66.7% fast, 33.3% slow")
emit()
emit("Delta (coord fast% - sidecar fast%) by burst:")
for burst in BURSTS:
    c_c = per_burst["coord"][burst]
    s_c = per_burst["sidecar"][burst]
    c_tot = sum(c_c.values()) or 1
    s_tot = sum(s_c.values()) or 1
    c_fp = 100.0 * (c_c.get("fast_A",0) + c_c.get("fast_B",0)) / c_tot
    s_fp = 100.0 * (s_c.get("fast_A",0) + s_c.get("fast_B",0)) / s_tot
    emit(f"  burst {burst:>4}:  coord={c_fp:5.1f}%  sidecar={s_fp:5.1f}%  delta={c_fp - s_fp:+5.1f}pp")


# ------------------------------------------------------------------
# Charts
# ------------------------------------------------------------------
FAST = "#2b6cb0"
SLOW = "#c05621"


def plot_fast_vs_slow_by_burst():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    xs = np.arange(len(BURSTS))
    width = 0.35
    for ax, side in zip(axes, ("coord", "sidecar")):
        fasts = []
        slows = []
        for burst in BURSTS:
            c = per_burst[side][burst]
            fasts.append(c.get("fast_A", 0) + c.get("fast_B", 0))
            slows.append(c.get("slow_A", 0) + c.get("slow_B", 0))
        ax.bar(xs - width/2, fasts, width, color=FAST, label="→ fast pods")
        ax.bar(xs + width/2, slows, width, color=SLOW, label="→ slow pods")
        # annotate fast% above the fast bar
        for i, (f, s) in enumerate(zip(fasts, slows)):
            tot = f + s
            if tot:
                pc = 100.0 * f / tot
                ax.text(i - width/2, f + 1, f"{pc:.0f}%", ha="center",
                        fontsize=8, color=FAST)
        ax.axhline(0, color="k", lw=0.5)
        ax.set_xticks(xs)
        ax.set_xticklabels([str(b) for b in BURSTS])
        ax.set_xlabel("burst size")
        ax.set_ylabel("requests routed to variant")
        ax.set_title(side)
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("Per-burst decode routing: fast vs slow pod assignments")
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / "fast_vs_slow_by_burst.png", dpi=130)
    plt.close(fig)


def plot_timeline(burst, fname):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, side in zip(axes, ("coord", "sidecar")):
        s = sides[side]
        w = s["windows"].get(burst)
        if not w:
            ax.set_title(f"{side} — no data for burst {burst}")
            continue
        t0, t1 = w
        # cumulative counters per pod-key
        pod_order = ["fast_A", "fast_B", "slow_A", "slow_B"]
        events = defaultdict(list)  # pod_key -> list of (t_offset)
        for r in s["routes"]:
            if t0 <= r["ts"] <= t1:
                events[s["pod_keys"][r["ip"]]].append(r["ts"] - t0)
        for pk in pod_order:
            evs = sorted(events.get(pk, []))
            cum = list(range(1, len(evs) + 1))
            color = FAST if pk.startswith("fast") else SLOW
            ls = "-" if pk.endswith("_A") else "--"
            ax.plot(evs, cum, color=color, ls=ls, label=f"{pk}")
        ax.set_xlim(0, t1 - t0)
        ax.set_xlabel("seconds since burst start")
        ax.set_ylabel("cumulative decode assignments")
        ax.set_title(f"{side} — burst {burst}")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7)
    fig.suptitle(f"Cumulative decode-pod assignments over burst {burst}")
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / fname, dpi=130)
    plt.close(fig)


def plot_per_pod():
    fig, ax = plt.subplots(figsize=(11, 5))
    xs = np.arange(len(BURSTS) * 2)  # 2 sides
    width = 0.2
    pod_order = ["fast_A", "fast_B", "slow_A", "slow_B"]
    pod_colors = [FAST, FAST, SLOW, SLOW]
    pod_hatches = [None, "///", None, "///"]
    for i, pk in enumerate(pod_order):
        vals = []
        for burst in BURSTS:
            for side in ("coord", "sidecar"):
                vals.append(per_burst[side][burst].get(pk, 0))
        ax.bar(xs + (i - 1.5) * width, vals, width,
               color=pod_colors[i], hatch=pod_hatches[i],
               edgecolor="white", label=pk)
    ax.set_xticks(xs)
    labels = []
    for burst in BURSTS:
        for side in ("c", "s"):
            labels.append(f"{burst}{side}")
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_xlabel("burst_size (c=coord, s=sidecar)")
    ax.set_ylabel("assignments to pod")
    ax.set_title("Per-pod decode assignments by side and burst")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(BASE / "analysis" / "per_pod_assignments.png", dpi=130)
    plt.close(fig)


plot_fast_vs_slow_by_burst()
plot_timeline(64, "routing_timeline_b64.png")
plot_timeline(128, "routing_timeline_b128.png")
plot_per_pod()

# Save summary
with open(BASE / "analysis" / "routing_summary.txt", "w") as f:
    f.write("\n".join(lines_out) + "\n")

print("\nsaved 4 PNGs and routing_summary.txt to analysis/")
