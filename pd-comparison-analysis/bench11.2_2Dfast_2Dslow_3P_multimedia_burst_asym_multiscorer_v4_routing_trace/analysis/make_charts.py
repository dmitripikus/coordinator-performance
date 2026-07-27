import matplotlib.pyplot as plt

BASE = "/Users/dpikus/PROJECTS/llm-d/repos/coordinator-performance/pd-comparison-analysis/bench11.2_2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_v4_routing_trace"

BURST = [8, 16, 32, 64, 128, 256]
ARCHS = {"coord": "#2b6cb0", "sidecar": "#c05621"}

# Parsed directly from each side's sglang bench_serving "Serving Benchmark Result" blocks.
# coord log:    coord/pod_logs_dpikus-epd-sglang-bench_20260726_183841/sglang_bench.log
# sidecar log:  sidecar/pod_logs_dpikus-pd-sglang-bench_20260726_192629/sglang_bench.log
# Fleet: 2 fast (--max-num-seqs=8) + 2 slow (--max-num-seqs=4) = 24 slots per side.
# Same fleet + scoring profile as 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed; this run patches all 3 EPPs to --v=4 and captures
# per-request "Request handled" routing traces (see analysis/ROUTING_MECHANISM.md).
DATA = {
    "coord": {
        "e2e_median":  [ 28829,  29560,  34271,  56378,  88135, 157077],
        "e2e_p90":     [ 30384,  30762,  55465,  84368, 155269, 300979],
        "ttft_median": [  5207,   3926,   5307,  30089,  60923, 130496],
        "ttft_p90":    [  5855,   5561,  30680,  59679, 130598, 275652],
        "tpot_median": [ 12.17,  12.56,  13.33,  13.00,  13.26,  13.02],
        "itl_median":  [ 11.94,  12.46,  13.18,  12.88,  12.77,  12.71],
        "itl_p90":     [ 12.50,  13.41,  15.06,  14.37,  15.18,  14.63],
        "output_tok_s":[523.49, 991.00,1104.18,1213.81,1254.45,1337.11],
    },
    "sidecar": {
        "e2e_median":  [ 28558,  28426,  35481,  57541,  88614, 160231],
        "e2e_p90":     [ 30277,  30607,  52873, 103478, 178350, 335429],
        "ttft_median": [  4261,   3106,   5736,  29459,  59285, 133929],
        "ttft_p90":    [  5852,   5663,  27467,  77816, 152997, 310084],
        "tpot_median": [ 12.12,  12.66,  13.46,  13.08,  13.08,  12.99],
        "itl_median":  [ 11.93,  12.50,  12.81,  12.81,  12.82,  12.81],
        "itl_p90":     [ 12.13,  12.79,  15.26,  14.91,  14.39,  14.11],
        "output_tok_s":[525.91,1035.19,1134.17,1198.25,1222.60,1175.68],
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
    "asymmetric fleet: 2 fast (max-num-seqs=8) + 2 slow (max-num-seqs=4); multi-scorer EPP; V(4) routing trace",
    "ttft_vs_burst.png",
)
plot_median_p90(
    "e2e_median", "e2e_p90", "end-to-end latency (ms)",
    "End-to-end request latency vs burst size (median, shaded to p90)",
    "e2e_latency_vs_burst.png",
)
plot_median_p90(
    "itl_median", "itl_p90", "inter-token latency (ms)",
    "Inter-token latency vs burst size (median, shaded to p90)",
    "itl_vs_burst.png",
)
plot_simple(
    "tpot_median", "time_per_output_token (ms)",
    "Time per output token (median) vs burst size",
    "tpot_vs_burst.png",
)
plot_simple(
    "output_tok_s", "output tokens / second",
    "Aggregate output-token throughput vs burst size",
    "output_throughput_vs_burst.png",
)

print("saved 5 PNGs to analysis/")
