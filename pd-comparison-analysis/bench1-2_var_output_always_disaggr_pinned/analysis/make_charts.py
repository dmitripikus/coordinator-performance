import glob
import json
import re

import matplotlib.pyplot as plt

SIZES = [100, 500, 1000, 2500]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}
BASE = "/Users/alexey/projects/coordinator-performance/pd-comparison-analysis/bench1-2_var_output_always_disaggr_pinned"


def load(arch):
    by_size = {}
    dirs = glob.glob(f"{BASE}/{arch}/inference-perf_*_random_250_*_isl_osl_*")
    dirs = [d for d in dirs if "old" not in d.lower()]
    for d in dirs:
        m = re.search(r"random_250_(\d+)_isl_osl", d)
        size = int(m.group(1))
        if size not in SIZES:
            continue
        f = f"{d}/summary_lifecycle_metrics.json"
        by_size[size] = json.load(open(f))
    return by_size


data = {arch: load(arch) for arch in ARCHS}


def series(metric_path, scale=1.0):
    out = {}
    for arch in ARCHS:
        p10, med, p90, mean, x = [], [], [], [], []
        for size in SIZES:
            d = data[arch].get(size)
            if not d:
                continue
            node = d["successes"]["latency"]
            for key in metric_path:
                node = node.get(key) if node else None
            if node is None:
                continue
            x.append(size)
            p10.append(node["p10"] * scale)
            med.append(node["median"] * scale)
            p90.append(node["p90"] * scale)
            mean.append(node["mean"] * scale)
        out[arch] = (x, p10, med, p90, mean)
    return out


def plot_distribution(metric_path, scale, ylabel, title, fname, overlay_metric_path=None, overlay_label=None,
                       show_mean=False):
    s = series(metric_path, scale)
    overlay = series(overlay_metric_path, scale) if overlay_metric_path else None
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for arch, color in ARCHS.items():
        x, p10, med, p90, mean = s[arch]
        if not x:
            continue
        ax.fill_between(x, p10, p90, color=color, alpha=0.15, label=f"{arch} p10-p90")
        ax.plot(x, med, color=color, marker="o", linewidth=2, label=f"{arch} median")
        if show_mean:
            ax.plot(x, mean, color=color, marker="^", markersize=5, linewidth=1.3,
                    linestyle=":", alpha=0.9, label=f"{arch} mean")
        if overlay:
            ox, _, omed, _, _ = overlay[arch]
            if ox:
                ax.plot(ox, omed, color=color, marker="s", markersize=4, linewidth=1.3,
                        linestyle="--", alpha=0.8, label=f"{arch} {overlay_label} median")
    ax.set_xscale("log")
    ax.set_xticks(SIZES)
    ax.set_xticklabels([str(sz) for sz in SIZES])
    ax.set_xlabel("output tokens")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{BASE}/analysis/{fname}", dpi=130)
    plt.close(fig)


plot_distribution(
    ["time_to_first_token"], 1000, "TTFT (ms)",
    "Time to first token vs output size (p10-median-p90)", "ttft_distribution.png",
)
plot_distribution(
    ["request_latency"], 1000, "request latency (ms)",
    "Request latency vs output size (p10-median-p90)", "request_latency_distribution.png",
)
plot_distribution(
    ["inter_token_latency"], 1000, "inter-token latency (ms)",
    "Inter-token latency vs output size (p10-median-p90)", "itl_distribution.png",
)
plot_distribution(
    ["time_per_output_token"], 1000, "time_per_output_token (ms)",
    "time_per_output_token vs output size (p10-median-p90)\n"
    "dotted = TPOT mean, dashed = ITL median, for comparison",
    "tpot_distribution.png",
    overlay_metric_path=["inter_token_latency"], overlay_label="ITL",
    show_mean=True,
)
plot_distribution(
    ["normalized_time_per_output_token"], 1000, "normalized_time_per_output_token (ms)",
    "normalized_time_per_output_token vs output size (p10-median-p90)", "ntpot_distribution.png",
)

# success rate bar chart
fig, ax = plt.subplots(figsize=(7, 4))
width = 0.35
xpos = range(len(SIZES))
for i, (arch, color) in enumerate(ARCHS.items()):
    rates = []
    for size in SIZES:
        d = data[arch].get(size)
        if not d:
            rates.append(0)
            continue
        total = d["successes"]["count"] + d.get("failures", {}).get("count", 0)
        rates.append(100.0 * d["successes"]["count"] / total if total else 0)
    offset = (i - 0.5) * width
    ax.bar([p + offset for p in xpos], rates, width=width, color=color, label=arch)
ax.set_xticks(list(xpos))
ax.set_xticklabels([str(sz) for sz in SIZES])
ax.set_xlabel("output tokens")
ax.set_ylabel("success rate (%)")
ax.set_ylim(0, 110)
ax.set_title("Request success rate vs output size")
ax.legend()
ax.grid(True, axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(f"{BASE}/analysis/success_rate.png", dpi=130)
plt.close(fig)

print("done")
