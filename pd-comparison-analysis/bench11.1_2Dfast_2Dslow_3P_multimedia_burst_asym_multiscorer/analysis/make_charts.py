import matplotlib.pyplot as plt

BASE = "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/pd-comparison-analysis/bench11.1_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_fix2"

BURST = [8, 16, 32, 64, 128, 256]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}

# Parsed directly from each side's sglang bench_serving "Serving Benchmark Result" blocks.
# coord log:    coord/pod_logs_dpikus-epd-sglang-bench_20260726_120117/sglang_bench.log
# sidecar log:  sidecar/pod_logs_dpikus-pd-sglang-bench_20260726_125241/sglang_bench.log
# Fleet: 2 fast (--max-num-seqs=8) + 2 slow (--max-num-seqs=4) = 24 slots per side.
# Same fleet + scoring profile as bench11; only difference is client-side --extra-request-body
# (adds skip_special_tokens=false + stream_options.include_usage=true to make ITL trustworthy).
DATA = {
    "coord": {
        "e2e_median":  [ 28823,  29135,  33467,  55277,  87123, 158508],
        "e2e_p90":     [ 29998,  30478,  55565,  80911, 156494, 327056],
        "ttft_median": [  4722,   4200,   5370,  29303,  60320, 132574],
        "ttft_p90":    [  5979,   5850,  31200,  56091, 130702, 300953],
        "tpot_median": [ 12.19,  12.53,  13.17,  12.88,  13.12,  13.03],
        "itl_median":  [ 11.97,  12.37,  12.63,  12.66,  12.79,  12.73],
        "itl_p90":     [ 13.88,  13.46,  14.46,  14.44,  14.53,  14.50],
        "output_tok_s":[529.49,1003.38,1105.91,1196.78,1215.09,1257.56],
    },
    "sidecar": {
        "e2e_median":  [ 29099,  28991,  32754,  56325,  87788, 158597],
        "e2e_p90":     [ 29655,  30358,  53749,  94215, 176722, 338721],
        "ttft_median": [  4462,   3809,   5190,  29457,  59765, 132040],
        "ttft_p90":    [  5860,   5726,  28250,  69707, 151344, 313565],
        "tpot_median": [ 11.99,  12.55,  13.20,  13.16,  13.04,  12.92],
        "itl_median":  [ 11.84,  12.42,  12.77,  12.85,  12.83,  12.62],
        "itl_p90":     [ 12.19,  12.81,  13.86,  14.46,  14.88,  14.21],
        "output_tok_s":[538.15,1029.44,1122.98,1211.05,1118.15,1190.15],
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
    "with skip_special_tokens=false: ITL now tracks wire cadence on both sides",
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
