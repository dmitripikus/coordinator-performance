# Runtime log-level changes for `llm-d-inference-gateway-istio`

Temporary log-level changes on the Istio gateway's Envoy proxy. Applied live
via the Envoy admin API — **no pod restart**, **reverts on pod restart** to the
level baked into the Deployment args (`--proxyLogLevel warn`,
`--proxyComponentLogLevel misc:warn`).

## Setup

```bash
export NS=dpikus-epd     # or dpikus-epd — match the namespace your gateway lives in
export POD=$(kubectl get pod -n $NS -l gateway.networking.k8s.io/gateway-name=llm-d-inference-gateway -o jsonpath='{.items[0].metadata.name}')
```

## View current levels

`/logging` is POST-only in Envoy, even to read.

```bash
kubectl exec -n $NS $POD -c istio-proxy -- \
  pilot-agent request POST 'logging'
```

## Set levels

### All components at once

```bash
kubectl exec -n $NS $POD -c istio-proxy -- \
  pilot-agent request POST 'logging?level=info'
```

Valid levels: `trace`, `debug`, `info`, `warning`, `error`, `critical`, `off`.

### One component (recommended — much less noise)

```bash
# Per-request HTTP lines
kubectl exec -n $NS $POD -c istio-proxy -- \
  pilot-agent request POST 'logging?http=info'

# Routing decisions
kubectl exec -n $NS $POD -c istio-proxy -- \
  pilot-agent request POST 'logging?router=debug'

# ext-proc / EPP path
kubectl exec -n $NS $POD -c istio-proxy -- \
  pilot-agent request POST 'logging?ext_proc=debug'
```

Handy components: `http`, `router`, `ext_proc`, `connection`, `upstream`, `filter`.

### Restore

```bash
kubectl exec -n $NS $POD -c istio-proxy -- \
  pilot-agent request POST 'logging?level=warn'
```

## Alternative — `istioctl`

If `istioctl` is installed locally, it wraps the admin call:

```bash
istioctl proxy-config log $POD.$NS                     # view
istioctl proxy-config log $POD.$NS --level info        # set all
istioctl proxy-config log $POD.$NS --level http:info   # set one
istioctl proxy-config log $POD.$NS --level http:info,ext_proc:debug   # multiple
```

## Watch the logs

```bash
kubectl logs -n $NS $POD -f --tail=100
```

## What persists, what doesn't

| Event                                            | Runtime level survives? |
|--------------------------------------------------|-------------------------|
| Traffic                                          | yes                     |
| Config push from istiod (routes, EnvoyFilters)   | yes                     |
| Certificate rotation                             | yes                     |
| Pod / container restart                          | **no** — reverts        |
| Deployment rollout, image update                 | **no** — reverts        |

For persistent levels, add `proxy.istio.io/config` to the `Gateway` resource
instead — that survives restarts.

## Typical debug flow

1. Turn on the component(s) you need.
2. Tail logs in another terminal.
3. Send the request (e.g. with a known `x-request-id`).
4. Grep for what you're looking for.
5. Restore `warn` to keep logs quiet.
