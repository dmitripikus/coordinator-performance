import matplotlib.pyplot as plt

BASE = "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/pd-comparison-analysis/bench10_4Dx2GPU_3Px2GPU_multimedia_burst_constrained"

BURST = [8, 16, 32, 64, 128, 256]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}

# Parsed directly from each side's sglang bench_serving "Serving Benchmark Result" blocks.
# coord log:    coord/bench_config/sglang-bench-bvnd9.log
# sidecar log:  sidecar/bench_config/sglang-bench-79vt4.log
DATA = {
    "coord": {
        "e2e_median":  [28755.41,  28682.41,  33419.45,  46320.52,  73062.11, 127788.39],
        "e2e_p90":     [30056.06,  30596.83,  35660.78,  62960.97, 117771.73, 223273.55],
        "ttft_median": [ 4805.23,   3506.41,   5239.31,  17950.59,  45195.62, 100027.96],
        "ttft_p90":    [ 5857.07,   5593.63,   8445.14,  35187.71,  88875.76, 194460.02],
        "tpot_median": [   12.02,     12.60,     14.02,     13.88,     13.82,     13.83],
        "itl_median":  [   12.02,     25.19,     14.41,     14.63,     13.93,     13.90],
        "itl_p90":     [   36.16,     37.79,     42.60,     42.45,     41.92,     41.46],
        "output_tok_s":[  531.53,   1038.16,   1728.06,   1964.62,   2091.84,   2194.70],
    },
    "sidecar": {
        "e2e_median":  [28301.43,  29101.50,  32165.44,  45288.39,  73737.91, 128204.30],
        "e2e_p90":     [29640.99,  30693.77,  35277.84,  62167.76, 117446.48, 224116.47],
        "ttft_median": [ 4240.58,   3173.73,   5186.73,  17531.01,  46217.71, 100195.46],
        "ttft_p90":    [ 5804.62,   5627.80,   7749.15,  34604.93,  89164.58, 195137.29],
        "tpot_median": [   12.03,     12.57,     13.61,     13.83,     13.93,     13.79],
        "itl_median":  [   35.04,     25.27,     14.49,     14.87,     14.04,     14.11],
        "itl_p90":     [   35.98,     38.03,     41.46,     41.62,     42.20,     41.79],
        "output_tok_s":[  536.91,   1026.86,   1743.81,   2014.43,   2105.50,   2145.20],
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
    ax.axvline(32, color="#666", linestyle="--", linewidth=1, alpha=0.6)
    ax.text(32, ax.get_ylim()[1] * 0.98, " decode cliff (4×8=32)",
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
    ax.axvline(32, color="#666", linestyle="--", linewidth=1, alpha=0.6)
    ax.text(32, ax.get_ylim()[1] * 0.98, " decode cliff (4×8=32)",
            fontsize=8, color="#666", va="top", ha="left")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{BASE}/analysis/{fname}", dpi=130)
    plt.close(fig)


plot_median_p90(
    "ttft_median", "ttft_p90", "TTFT (ms)",
    "Time to first token vs burst size (median, shaded to p90)\nmultimodal: [1-5] random 1080p JPEG + ~300 text tokens/request, decode capped at 8 seqs/pod",
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
