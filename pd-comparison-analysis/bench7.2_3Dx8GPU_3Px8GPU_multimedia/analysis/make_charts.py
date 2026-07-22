import matplotlib.pyplot as plt

BASE = "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/pd-comparison-analysis/bench7.2_3Dx8GPU_3Px8GPU_multimedia"

CONCURRENCY = [10, 20, 30, 40]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}

# Parsed directly from each side's sglang bench_serving "Serving Benchmark Result" blocks.
# bench7.2 coord = fresh coord run (sglang-bench-t9zxz.log).
# sidecar values are identical to bench7.1 — the sidecar directory in bench7.2 is a
# byte-identical copy of bench7.1/sidecar (verified via diff), so we compare
# bench7.2's coord numbers against the same sidecar baseline.
DATA = {
    "coord": {
        "e2e_median": [23173.61, 37200.34, 64228.99, 69565.38],
        "e2e_p90": [37036.89, 60076.82, 89497.06, 95726.47],
        "ttft_median": [4834.60, 5717.49, 7581.23, 8875.03],
        "ttft_p90": [6892.30, 8654.79, 10739.39, 12191.92],
        "tpot_median": [27.56, 38.60, 53.71, 58.92],
        "itl_median": [35.38, 49.37, 59.78, 68.05],
        "itl_p90": [70.28, 95.10, 120.67, 134.76],
        "output_tok_s": [174.96, 223.55, 311.19, 343.66],
        "req_s": [0.24, 0.27, 0.32, 0.36],
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
