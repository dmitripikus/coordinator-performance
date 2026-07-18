import glob
import json
import re

import matplotlib.pyplot as plt

SIZES = [100, 500, 1000]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}
BASE = "/Users/alexey/projects/coordinator-performance/pd-comparison-analysis/bench1-2_var_output_always_disaggr"


def load(arch):
    by_size = {}
    by_size_epoch = {}
    dirs = glob.glob(f"{BASE}/{arch}/inference-perf_*_random_250_*_isl_osl_*")
    dirs = [d for d in dirs if "old" not in d.lower()]
    for d in dirs:
        m = re.search(r"random_250_(\d+)_isl_osl", d)
        size = int(m.group(1))
        if size not in SIZES:
            continue
        f = f"{d}/summary_lifecycle_metrics.json"
        if not glob.glob(f):
            continue
        epoch = int(re.search(r"inference-perf_(\d+)_", d).group(1))
        if size not in by_size_epoch or epoch > by_size_epoch[size]:
            by_size_epoch[size] = epoch
            by_size[size] = json.load(open(f))
    return by_size


data = {arch: load(arch) for arch in ARCHS}


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


def plot_distribution(metric_path, scale, ylabel, title, fname):
    s = series(metric_path, scale)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for arch, color in ARCHS.items():
        x, p10, med, p90 = s[arch]
        if not x:
            continue
        ax.fill_between(x, p10, p90, color=color, alpha=0.15, label=f"{arch} p10-p90")
        ax.plot(x, med, color=color, marker="o", linewidth=2, label=f"{arch} median")
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
    "time_per_output_token vs output size (p10-median-p90)", "tpot_distribution.png",
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

# sidecar 250->1000 output: same test, three attempts on three different
# decode nodes (node variance investigation)
NODE_RUNS = [
    ("g11bab6\n(attempt 1)", f"{BASE}/sidecar/inference-perf_1784391367_random_250_1000_isl_osl_pd-gpt-oss-120b-old"),
    ("gc37d06\n(attempt 2)", f"{BASE}/sidecar/inference-perf_1784400246_random_250_1000_isl_osl_pd-gpt-oss-120b-old2"),
    ("gf2a19e\n(attempt 3,\npinned)", f"{BASE}/sidecar/inference-perf_1784404017_random_250_1000_isl_osl_pd-gpt-oss-120b"),
]
node_data = [(label, json.load(open(f"{d}/summary_lifecycle_metrics.json"))) for label, d in NODE_RUNS]

fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
colors = ["#c05621", "#c05621", "#2b7a4b"]  # highlight the pinned/matched attempt in green

for ax, metric_path, scale, ylabel, title in [
    (axes[0], ["inter_token_latency"], 1000, "ITL (ms)", "Inter-token latency by decode node"),
    (axes[1], ["request_latency"], 1000, "request latency (ms)", "Request latency by decode node"),
]:
    labels, meds, p10s, p90s = [], [], [], []
    for label, d in node_data:
        node = d["successes"]["latency"]
        for key in metric_path:
            node = node[key]
        labels.append(label)
        meds.append(node["median"] * scale)
        p10s.append(node["median"] * scale - node["p10"] * scale)
        p90s.append(node["p90"] * scale - node["median"] * scale)
    xpos = range(len(labels))
    ax.bar(xpos, meds, color=colors, alpha=0.85)
    ax.errorbar(xpos, meds, yerr=[p10s, p90s], fmt="none", ecolor="black", capsize=5, linewidth=1.5)
    ax.set_xticks(list(xpos))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=10)
    ax.grid(True, axis="y", alpha=0.3)
    for i, v in enumerate(meds):
        ax.text(i, v, f"{v:.2f}" if scale == 1000 and metric_path == ["inter_token_latency"] else f"{v:.0f}",
                ha="center", va="bottom", fontsize=8)

fig.suptitle("Sidecar, 250-input/1,000-output: same test, three decode nodes\n(error bars = p10-p90)", fontsize=11)
fig.tight_layout()
fig.savefig(f"{BASE}/analysis/node_variance_1000output.png", dpi=130)
plt.close(fig)

print("done")
