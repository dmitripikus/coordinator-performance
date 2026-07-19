import matplotlib.pyplot as plt

BASE = "/Users/alexey/projects/coordinator-performance/pd-comparison-analysis/bench7.1_3Dx8GPU_3Px8GPU_multimedia"

CONCURRENCY = [10, 20, 30, 40]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}

# Parsed directly from each side's sglang bench_serving "Serving Benchmark Result" blocks.
DATA = {
    "coord": {
        "e2e_median": [34527.79, 56481.08, 80843.93, 101494.61],
        "e2e_p90": [62683.31, 98505.01, 143004.47, 165427.93],
        "ttft_median": [22220.75, 40262.77, 52929.11, 66732.06],
        "ttft_p90": [38738.27, 63997.78, 90077.51, 104535.77],
        "tpot_median": [19.12, 19.79, 24.21, 27.87],
        "itl_median": [20.05, 21.76, 29.40, 31.56],
        "itl_p90": [29.47, 34.78, 45.32, 49.08],
        "output_tok_s": [103.86, 146.89, 184.75, 216.90],
        "req_s": [0.14, 0.18, 0.19, 0.23],
    },
    "sidecar": {
        "e2e_median": [22629.38, 32455.13, 55383.09, 66567.23],
        "e2e_p90": [39463.90, 58160.47, 86729.88, 93752.66],
        "ttft_median": [4177.27, 5642.51, 6726.72, 8202.60],
        "ttft_p90": [5695.82, 7711.96, 9274.06, 12750.34],
        "tpot_median": [31.60, 36.98, 52.02, 57.61],
        "itl_median": [36.38, 50.62, 68.59, 73.28],
        "itl_p90": [73.75, 91.28, 117.92, 136.87],
        "output_tok_s": [182.77, 247.48, 294.94, 388.90],
        "req_s": [0.25, 0.30, 0.30, 0.41],
    },
}


def plot_median_p90(metric_median, metric_p90, ylabel, title, fname):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for arch, color in ARCHS.items():
        med = DATA[arch][metric_median]
        ax.plot(CONCURRENCY, med, color=color, marker="o", linewidth=2, label=f"{arch} median")
        if metric_p90:
            p90 = DATA[arch][metric_p90]
            ax.fill_between(CONCURRENCY, med, p90, color=color, alpha=0.15, label=f"{arch} median-p90")
    ax.set_xlabel("concurrency level")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xticks(CONCURRENCY)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{BASE}/analysis/{fname}", dpi=130)
    plt.close(fig)


def plot_simple(metric, ylabel, title, fname):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for arch, color in ARCHS.items():
        ax.plot(CONCURRENCY, DATA[arch][metric], color=color, marker="o", linewidth=2, label=arch)
    ax.set_xlabel("concurrency level")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xticks(CONCURRENCY)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{BASE}/analysis/{fname}", dpi=130)
    plt.close(fig)


plot_median_p90(
    "ttft_median", "ttft_p90", "TTFT (ms)",
    "Time to first token vs concurrency (median, shaded to p90)\nmultimodal: ~300 text + ~4,700 vision tokens/request",
    "ttft_vs_concurrency.png",
)
plot_median_p90(
    "e2e_median", "e2e_p90", "end-to-end latency (ms)",
    "End-to-end request latency vs concurrency (median, shaded to p90)",
    "e2e_latency_vs_concurrency.png",
)
plot_median_p90(
    "itl_median", "itl_p90", "inter-token latency (ms)",
    "Inter-token latency vs concurrency (median, shaded to p90)",
    "itl_vs_concurrency.png",
)
plot_simple(
    "tpot_median", "time_per_output_token (ms)",
    "Time per output token vs concurrency (median)",
    "tpot_vs_concurrency.png",
)
plot_simple(
    "output_tok_s", "output tokens/sec",
    "Output token throughput vs concurrency",
    "output_throughput_vs_concurrency.png",
)

print("done")
