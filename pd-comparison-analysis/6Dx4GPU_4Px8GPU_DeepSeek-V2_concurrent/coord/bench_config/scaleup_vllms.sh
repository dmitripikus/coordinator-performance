kubectl scale deploy coord-disaggregation-nvidia-gpu-vllm-prefill --replicas=4

sleep 3
kubectl scale deploy coord-disaggregation-nvidia-gpu-vllm-decode --replicas=6

