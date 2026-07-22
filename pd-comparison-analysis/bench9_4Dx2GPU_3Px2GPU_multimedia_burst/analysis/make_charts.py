import matplotlib.pyplot as plt

BASE = "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/pd-comparison-analysis/bench9_4Dx2GPU_3Px2GPU_multimedia_burst"

BURST = [4, 8, 16, 32, 64, 128]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}

# Parsed directly from each side's sglang bench_serving "Serving Benchmark Result" blocks.
# coord log:    coord/bench_config/sglang-bench-hpsqc.log
# sidecar log:  sidecar/bench_config/sglang-bench-vttzt.log
DATA = {
    "coord": {
        "e2e_median": [27021.42, 26062.89, 27937.33, 30659.79, 37860.55, 49775.45],
        "e2e_p90":    [27900.71, 26802.83, 28880.99, 32407.18, 40087.62, 54020.64],
        "ttft_median":[3799.46,  2089.10,  3082.79,  3520.47,  6088.40,  10217.49],
        "ttft_p90":   [4660.32,  3205.05,  4314.72,  5864.61,  9514.16,  17094.59],
        "tpot_median":[11.62,    11.95,    12.42,    13.55,    15.84,    19.56],
        "itl_median": [11.72,    11.93,    12.47,    17.39,    16.41,    21.87],
        "itl_p90":    [34.96,    35.62,    37.29,    40.57,    46.98,    58.45],
        "output_tok_s":[284.48,  594.99,   1089.07,  1893.56,  3085.10,  4493.50],
    },
    "sidecar": {
        "e2e_median": [27288.40, 26329.36, 27847.95, 30618.08, 37886.94, 48714.38],
        "e2e_p90":    [27743.93, 27041.62, 29398.40, 32249.16, 40167.55, 53213.35],
        "ttft_median":[4093.01,  2698.32,  2971.82,  3596.20,  6096.46,  9177.76],
        "ttft_p90":   [4530.72,  3253.36,  4705.14,  5793.35,  9683.72,  16538.13],
        "tpot_median":[11.62,    11.95,    12.42,    13.54,    15.82,    19.54],
        "itl_median": [34.59,    34.60,    33.77,    24.16,    30.68,    21.71],
        "itl_p90":    [35.00,    35.65,    37.31,    40.50,    47.11,    58.37],
        "output_tok_s":[286.28,  589.29,   1078.11,  1950.17,  3095.03,  4615.28],
    },
}


def plot_median_p90(metric_median, metric_p90, ylabel, title, fname):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for arch, color in ARCHS.items():
        med = DATA[arch][metric_median]
        ax.plot(BURST, med, color=color, marker="o", linewidth=2, label=f"{arch} median")
        if metric_p90:
            p90 = DATA[arch][metric_p90]
            ax.fill_between(BURST, med, p90, color=color, alpha=0.15, label=f"{arch} median-p90")
    ax.set_xlabel("burst size (num_prompts, requests arriving in <1s)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xscale("log", base=2)
    ax.set_xticks(BURST)
    ax.set_xticklabels([str(b) for b in BURST])
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{BASE}/analysis/{fname}", dpi=130)
    plt.close(fig)


def plot_simple(metric, ylabel, title, fname):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for arch, color in ARCHS.items():
        ax.plot(BURST, DATA[arch][metric], color=color, marker="o", linewidth=2, label=arch)
    ax.set_xlabel("burst size (num_prompts, requests arriving in <1s)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xscale("log", base=2)
    ax.set_xticks(BURST)
    ax.set_xticklabels([str(b) for b in BURST])
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{BASE}/analysis/{fname}", dpi=130)
    plt.close(fig)


plot_median_p90(
    "ttft_median", "ttft_p90", "TTFT (ms)",
    "Time to first token vs burst size (median, shaded to p90)\nmultimodal: 3 x 1080p JPEG + ~300 text tokens/request",
    "ttft_vs_burst.png",
)
plot_median_p90(
    "e2e_median", "e2e_p90", "end-to-end latency (ms)",
    "End-to-end request latency vs burst size (median, shaded to p90)",
    "e2e_latency_vs_burst.png",
)
plot_median_p90(
    "itl_median", "itl_p90", "inter-token latency (ms)",
    "Inter-token latency vs burst size (median, shaded to p90)\nsidecar routing-proxy coalesces streamed tokens at low bursts",
    "itl_vs_burst.png",
)
plot_simple(
    "tpot_median", "time_per_output_token (ms)",
    "Time per output token vs burst size (median)",
    "tpot_vs_burst.png",
)
plot_simple(
    "output_tok_s", "output tokens/sec",
    "Output token throughput vs burst size",
    "output_throughput_vs_burst.png",
)

print("done")
