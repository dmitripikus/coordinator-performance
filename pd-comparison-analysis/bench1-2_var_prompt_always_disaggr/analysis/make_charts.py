import glob
import json
import re

import matplotlib.pyplot as plt

SIZES = [1, 10, 100, 1000, 10000]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}
BASE = "/Users/alexey/projects/coordinator-performance/pd-comparison-analysis/bench1-2_var_prompt_always_disaggr"


def load(arch):
    by_size = {}
    by_size_epoch = {}
    dirs = glob.glob(f"{BASE}/{arch}/inference-perf_*_random_*_250_isl_osl_*")
    dirs = [d for d in dirs if "old" not in d.lower()]
    for d in dirs:
        m = re.search(r"random_(\d+)_250_isl_osl", d)
        size = int(m.group(1))
        epoch = int(re.search(r"inference-perf_(\d+)_", d).group(1))
        if size not in by_size_epoch or epoch > by_size_epoch[size]:
            by_size_epoch[size] = epoch
            by_size[size] = json.load(open(f"{d}/summary_lifecycle_metrics.json"))
    return by_size


data = {arch: load(arch) for arch in ARCHS}

TP4_DIRS = {
    "coord": f"{BASE}/coord/inference-perf_1784372757_random_10000_250_tp_4_isl_osl_pd-gpt-oss-120b",
    "sidecar": f"{BASE}/sidecar/inference-perf_1784378200_random_10000_250_tp_4_isl_osl_pd-gpt-oss-120b",
}
tp4_data = {arch: json.load(open(f"{d}/summary_lifecycle_metrics.json")) for arch, d in TP4_DIRS.items()}
TP4_X = 10000  # exact same x as the TP=1 10000-token point


def series(metric_path, scale=1.0):
    out = {}
    for arch in ARCHS:
        p10, med, p90, x = [], [], [], []
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
        out[arch] = (x, p10, med, p90)
    return out


def tp4_point(arch, metric_path, scale):
    node = tp4_data[arch]["successes"]["latency"]
    for key in metric_path:
        node = node.get(key) if node else None
    if node is None:
        return None
    return node["p10"] * scale, node["median"] * scale, node["p90"] * scale


def plot_distribution(metric_path, scale, ylabel, title, fname):
    s = series(metric_path, scale)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for arch, color in ARCHS.items():
        x, p10, med, p90 = s[arch]
        if not x:
            continue
        ax.fill_between(x, p10, p90, color=color, alpha=0.15, label=f"{arch} p10-p90")
        ax.plot(x, med, color=color, marker="o", linewidth=2, label=f"{arch} median")

        tp4 = tp4_point(arch, metric_path, scale)
        if tp4 is not None and x and x[-1] == 10000:
            tp4_p10, tp4_med, tp4_p90 = tp4
            # dotted connector from the TP=1 10,000-token point to the TP=4 point
            ax.plot([10000, TP4_X], [med[-1], tp4_med], color=color, linestyle=":", linewidth=1.5, alpha=0.7)
            ax.errorbar(
                [TP4_X], [tp4_med], yerr=[[tp4_med - tp4_p10], [tp4_p90 - tp4_med]],
                color=color, marker="X", markersize=9, markeredgecolor="black",
                markeredgewidth=0.8, linewidth=1.5, capsize=4,
                label=f"{arch} TP=4 (prefill)",
            )

    ax.set_xscale("log")
    if TP4_X in SIZES:
        ax.set_xticks(SIZES)
        ax.set_xticklabels([str(sz) for sz in SIZES])
    else:
        ax.set_xticks(SIZES + [TP4_X])
        ax.set_xticklabels([str(sz) for sz in SIZES] + ["10000\n(prefill TP=4)"])
    ax.set_xlabel("input tokens")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{BASE}/analysis/{fname}", dpi=130)
    plt.close(fig)


plot_distribution(
    ["time_to_first_token"], 1000, "TTFT (ms)",
    "Time to first token vs prompt size (p10-median-p90)", "ttft_distribution.png",
)
plot_distribution(
    ["request_latency"], 1000, "request latency (ms)",
    "Request latency vs prompt size (p10-median-p90)", "request_latency_distribution.png",
)
plot_distribution(
    ["inter_token_latency"], 1000, "inter-token latency (ms)",
    "Inter-token latency vs prompt size (p10-median-p90)", "itl_distribution.png",
)
plot_distribution(
    ["time_per_output_token"], 1000, "time_per_output_token (ms)",
    "time_per_output_token vs prompt size (p10-median-p90)", "tpot_distribution.png",
)
plot_distribution(
    ["normalized_time_per_output_token"], 1000, "normalized_time_per_output_token (ms)",
    "normalized_time_per_output_token vs prompt size (p10-median-p90)", "ntpot_distribution.png",
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
ax.set_xticklabels([str(s) for s in SIZES])
ax.set_xlabel("input tokens")
ax.set_ylabel("success rate (%)")
ax.set_ylim(0, 110)
ax.set_title("Request success rate vs prompt size")
ax.legend()
ax.grid(True, axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(f"{BASE}/analysis/success_rate.png", dpi=130)
plt.close(fig)

print("done")
