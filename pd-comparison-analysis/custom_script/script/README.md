# Short prompt

# 1. Apply (creates ConfigMap + Deployment)
kubectl apply -f alexey-script-job.yaml

# 2. Wait for the pod to be Running
kubectl wait pod -l app=reqsend --for=condition=Ready --timeout=60s

# 3. Build and run inside the pod, capture output locally

## with reuse
```bash
kubectl exec -it deployment/reqsend -- bash -c \
  'cp /work/go.mod /tmp/ && cp /work/main.go /tmp/ && cd /tmp && go build -o reqsend main.go && \
   ./reqsend -host llm-d-inference-gateway-istio -port 80 -n 10 -model openai/gpt-oss-120b' \
  > with-coord-times-with-reuse.txt
```

## with no reuse
```bash
  kubectl exec -it deployment/reqsend -- bash -c \
  'cp /work/go.mod /tmp/ && cp /work/main.go /tmp/ && cd /tmp && go build -o reqsend main.go && \
   ./reqsend -host llm-d-inference-gateway-istio -port 80 -n 10 -model openai/gpt-oss-120b -reuse=false' \
  > with-coord-times-no-reuse.txt
 ``` 

 # Long prompt

 # 1. Apply (creates ConfigMap + Deployment)
kubectl apply -f alexey-script-job-long-prompt.yaml

# 2. Wait for the pod to be Running
kubectl wait pod -l app=reqsend-long --for=condition=Ready --timeout=60s

# 3. Build and run inside the pod, capture output locally

## with reuse
```bash
kubectl exec -it deployment/reqsend-long -- bash -c \
  'cp /work/go.mod /tmp/ && cp /work/main.go /tmp/ && cd /tmp && go build -o reqsend main.go && \
   ./reqsend -host llm-d-inference-gateway-istio -port 80 -n 10 -model openai/gpt-oss-120b' \
  > with-coord-long-prompt-times-with-reuse.txt
```

## with no reuse
```bash
  kubectl exec -it deployment/reqsend-long -- bash -c \
  'cp /work/go.mod /tmp/ && cp /work/main.go /tmp/ && cd /tmp && go build -o reqsend main.go && \
   ./reqsend -host llm-d-inference-gateway-istio -port 80 -n 10 -model openai/gpt-oss-120b -reuse=false' \
  > with-coord-long-prompt-times-no-reuse.txt
 ``` 