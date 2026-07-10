# bench4 — Gateway request trace (coordinator architecture)

Data: `gateway.log` — istio/Envoy proxy **debug** logs (`ext_proc: trace`,
`http/http2/connection: debug`) captured for **3 manual `/v1/completions`
requests** (curl), model `openai/gpt-oss-120b`, coordinator (EPD) setup,
ns `dpikus-epd`. Requests traced by `x-request-id`:

| x-request-id (suffix) | arrival (UTC) |
|---|---|
| …440005 | 13:57:33 (first after idle → cold) |
| …440006 | 13:58:51 (warm) |
| …440007 | 13:59:18 (warm) |

## Request flow through the gateway (confirmed from the log)

Each client `/v1/completions` is routed to the coordinator, which drives P/D as
**two separate legs back through the gateway** (same x-request-id, tagged
`epp-phase`). Each leg triggers **two** ext_proc (EPP) calls:

1. Client request arrives at gateway.
2. **prefill leg** — request-headers ext_proc → EPP **chooses prefill node** (sets `x-gateway-destination-endpoint`).
3. Gateway forwards to the chosen prefill pod.
4. Prefill model responds.
5. Response-headers ext_proc → EPP does almost nothing (sets `x-went-into-resp-headers: true`).
6. Gateway returns prefill response to the coordinator.
7. **decode leg** — coordinator sends decode request to gateway.
8. Request-headers ext_proc → EPP **chooses decode node**.
9. Gateway forwards to the chosen decode pod.
10. Response-headers ext_proc → EPP noop again.
11. Gateway streams decode response to the coordinator.

Evidence: `x-gateway-destination-endpoint` set **6×** (prefill+decode node choice
× 3 requests); `x-went-into-resp-headers` set **6×** (the noop response calls).

## Per-request gateway timeline (measured)

| Phase | …440005 (cold) | …440006 | …440007 |
|-------|---------:|---------:|---------:|
| Routing: client→prefill-leg arrival (route to coordinator + coordinator issues prefill) | 3.2 ms | 0.7 ms | 1.0 ms |
| **Prefill leg** (node-select ext_proc + prefill model + KV) | 318.8 ms | 52.5 ms | 51.6 ms |
| Handoff: prefill-done → decode-leg arrival | 1.8 ms | 0.3 ms | 0.3 ms |
| **Decode leg** (node-select ext_proc + decode model) | 372.5 ms | 121.8 ms | 120.2 ms |
| **Client-visible total** | **697.8 ms** | **175.6 ms** | **173.5 ms** |

### ext_proc / EPP cost (the routing filter itself)
| Call | cost |
|------|-----:|
| Node-selection ext_proc round-trip (request → EPP → response), per leg | **0.1 – 0.9 ms** |
| Response-path ext_proc (noop), per leg | ~0.4 ms |
| **Total coordinator non-model overhead** (both legs, all 4 ext_proc calls, coordinator hop), warm | **~1.0 – 1.4 ms** |

## Where the time is spent

- **Almost entirely model compute (prefill + decode), not the gateway.** The whole gateway + EPP + coordinator orchestration path is **~1 ms** when warm. Each ext_proc node-selection is sub-millisecond; the second (response) ext_proc per leg is a noop (~0.4 ms).
- **Warm requests (…006/…007):** decode ~121 ms (~69%) + prefill ~52 ms (~30%) + routing/orchestration ~1 ms (<1%) ≈ 175 ms.
- **The first request (…440005) is a cold outlier (~698 ms, ~4×)** — both prefill (319 vs ~52 ms) and decode (372 vs ~121 ms) inflated by model/cache warmup after idle, **not** gateway cost.

### Implication for the bench1 short-prompt TTFT gap (~18 ms coord vs sidecar)
The "two ext_proc vs one" is **not** where the 18 ms goes — ext_proc is sub-ms.
The coordinator's extra cost is the **separate, serialized prefill leg**
(cross-pod round-trip + KV-cache transfer to the decode pod) that the sidecar
collapses by sitting next to the decode server. Routing/ext_proc overhead is ~1 ms.

## Coordinator internal per-step timings (reference — different run)

⚠️ bench4 has **no coordinator log**, and the bench4 requests (…440005/6/7,
13:57-13:59 UTC) do **not** appear in the only available coordinator log
(`bench5/.../coordinator.log`, which covers 14:36-14:43 UTC — a separate 45 req/s
load test, 5000-in/250-out). So the coordinator's internal `parse/prefill/decode`
breakdown **cannot be mapped to the exact bench4 requests**. For reference, that
coordinator log's own orchestration overhead across **5850** requests is:

| Coordinator step | mean | p99 |
|------------------|-----:|----:|
| parse | 0.36 ms | 0.52 ms |
| orchestration (recv→prefill-send + prefill-done→decode-send) | **0.10 ms** | 0.18 ms |
| prefill leg (model+KV+queue) | 2694 ms | 16 221 ms |
| decode leg (model) | 3410 ms | 3826 ms |

This independently confirms the gateway finding: the coordinator's own
non-model orchestration is **~0.1 ms** — negligible. Request latency is prefill +
decode model time.

> To decompose the bench1 18 ms precisely, capture gateway debug logs (as here)
> for a coordinator **and** a sidecar run at the bench1 workload (1-in/15-out),
> then diff the client-arrival → first-decode-token timeline.
