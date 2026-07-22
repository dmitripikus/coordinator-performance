import matplotlib.pyplot as plt

BASE = "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/pd-comparison-analysis/bench11_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer"

BURST = [8, 16, 32, 64, 128, 256]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}

# Parsed directly from each side's sglang bench_serving "Serving Benchmark Result" blocks.
# coord log:    coord/bench_config/sglang-bench-7knqq.log
# sidecar log:  sidecar/bench_config/sglang-bench-hclcv.log
# Fleet: 2 fast (--max-num-seqs=8) + 2 slow (--max-num-seqs=4) = 24 slots per side.
DATA = {
    "coord": {
        "e2e_median":  [ 29040,  29184,  33381,  55907,  88225, 159759],
        "e2e_p90":     [ 29603,  31055,  55875,  82635, 178026, 315354],
        "ttft_median": [  4893,   3844,   5536,  29959,  60490, 133514],
        "ttft_p90":    [  5704,   6199,  30435,  58056, 152271, 290088],
        "tpot_median": [ 12.10,  12.63,  13.34,  13.24,  13.20,  13.23],
        "itl_median":  [ 23.72,  25.17,  14.58,  14.27,  14.05,  13.61],
        "itl_p90":     [ 36.05,  37.80,  40.54,  40.81,  40.78,  40.77],
        "output_tok_s":[532.50,1018.28,1120.63,1218.01,1226.50,1244.38],
    },
    "sidecar": {
        "e2e_median":  [ 28872,  28585,  32654,  56438,  89304, 161915],
        "e2e_p90":     [ 30418,  31027,  53851, 102837, 177536, 339817],
        "ttft_median": [  4624,   3176,   5417,  29794,  61249, 135642],
        "ttft_p90":    [  6123,   6135,  28610,  77193, 151848, 314318],
        "tpot_median": [ 12.09,  12.59,  13.07,  13.03,  13.23,  12.98],
        "itl_median":  [ 12.03,  36.76,  13.74,  14.88,  14.06,  13.75],
        "itl_p90":     [ 36.02,  38.16,  41.34,  41.01,  41.74,  40.29],
        "output_tok_s":[525.00,1003.29,1136.95,1193.23,1232.40,1174.85],
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
    ax.axvline(24, color="#666", linestyle="--", linewidth=1, alpha=0.6)
    ax.text(24, ax.get_ylim()[1] * 0.98, " fleet cap (2×8 + 2×4 = 24)",
            fontsize=8, color="#666", va="top", ha="left")
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
    ax.axvline(24, color="#666", linestyle="--", linewidth=1, alpha=0.6)
    ax.text(24, ax.get_ylim()[1] * 0.98, " fleet cap (2×8 + 2×4 = 24)",
            fontsize=8, color="#666", va="top", ha="left")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{BASE}/analysis/{fname}", dpi=130)
    plt.close(fig)


plot_median_p90(
    "ttft_median", "ttft_p90", "TTFT (ms)",
    "Time to first token vs burst size (median, shaded to p90)\n"
    "asymmetric fleet: 2 fast (max-num-seqs=8) + 2 slow (max-num-seqs=4); multi-scorer EPP",
    "ttft_vs_burst.png",
)
plot_median_p90(
    "e2e_median", "e2e_p90", "end-to-end latency (ms)",
    "End-to-end request latency vs burst size (median, shaded to p90)",
    "e2e_latency_vs_burst.png",
)
plot_median_p90(
    "itl_median", "itl_p90", "inter-token latency (ms)",
    "Inter-token latency vs burst size (median, shaded to p90)\n"
    "streaming coalescing dominates below fleet cap; real ITL above",
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
