#!/usr/bin/env bash
# The teacher (Ollama) runs on the laptop, outside the cluster. Expose it inside the
# cluster as the Service teacher.pipeline.svc:11434 via a selector-less Service whose
# Endpoints is the Docker gateway of the k3d network (= the laptop as seen from the node).
set -euo pipefail
gw=$(docker network inspect k3d-kdcloud -f '{{(index .IPAM.Config 0).Gateway}}')
echo "teacher endpoint: ${gw}:11434"
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata: {name: teacher, namespace: pipeline}
spec:
  ports: [{name: http, port: 11434, targetPort: 11434}]
---
apiVersion: v1
kind: Endpoints
metadata: {name: teacher, namespace: pipeline}
subsets:
  - addresses: [{ip: "${gw}"}]
    ports: [{name: http, port: 11434}]
EOF
