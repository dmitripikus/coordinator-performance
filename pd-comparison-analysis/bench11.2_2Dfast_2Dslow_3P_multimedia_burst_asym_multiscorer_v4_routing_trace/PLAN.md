# bench11.2 — re-run of 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed with EPP `--v=4` routing trace

## Purpose

The [2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed mechanism analysis](../2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed/analysis/MECHANISM.md)
concluded that the coord-vs-sidecar tail-latency win at bursts 64 and
128 is *consistent* with deferred-decode as the mechanism, but the
per-pod-load evidence alone was inconclusive because no log we had
recorded which decode pod each request was routed to. bench11.2 patches
all three EPPs (`coordinator-epd-decode-epp`, `coordinator-epd-prefill-epp`,
`pd-disaggregation-epp`) from `--v=2` to `--v=4` and re-runs the same
6-burst sweep (8/16/32/64/128/256) on both coord and sidecar sides,
capturing per-request routing decisions in the EPP logs.

The V(4) logs enable a direct test: **does coord route meaningfully more
decode requests to fast pods than sidecar does, and is the skew larger
at the win-zone bursts (64 and 128)?** If yes, deferred-decode is
confirmed as the mechanism. If no, we need a different hypothesis.

## Setup identical to 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed

Fleet, scoring profile, and workload are unchanged from 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed:
- 2 fast decode pods (`--max-num-seqs=8`) + 2 slow (`--max-num-seqs=4`) per side = 24 slots
- 3 prefill pods per side, `--max-num-seqs` unset
- 3-scorer decode profile: `kv-cache-utilization-scorer` (w=3) + `queue-scorer` (w=2) + `active-request-scorer` (w=1)
- 6-burst sweep with 60s quiesce between bursts; request-body fixes
  (`ignore_eos=true`, `skip_special_tokens=false`,
  `stream_options.include_usage=true`) preserved from 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed

Only difference: all three EPPs' `epp` container args are patched from
`--v=2` to `--v=4` before the run, then restored to `--v=2` after.

See the top-level plan file at
`/Users/dpikus/.claude/plans/i-need-to-check-starry-puzzle.md` for the
full methodology.

## Output artifacts (this directory)

- `coord/bench_config/benchmark-job.yaml` — copy of 2Dfast_2Dslow_3P_multimedia_burst_asym_multiscorer_request_body_fixed's (unchanged)
- `coord/pod_logs_.../` — collected logs incl. large `coordinator-epd-decode-epp-*/epp.log` at V(4)
- `sidecar/bench_config/benchmark-job.yaml`
- `sidecar/pod_logs_.../`
- `analysis/routing_analysis.py` — parser + charter for per-request routing decisions
- `analysis/routing_distribution.png`, `analysis/routing_timeline_b64.png`, `analysis/routing_timeline_b128.png`
- `analysis/ROUTING_MECHANISM.md` — verdict on whether deferred-decode is the mechanism
