#!/usr/bin/env bash
# Task 7: the standard Locust run through the Ingress, with `kubectl top pods` sampled every 10 s.
# Outputs: results/loadtest_* (Locust), results/task7_top_pods.txt, results/task7_locust_stdout.txt
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p results
kubectl -n app get pods -l app=parser -o wide > results/task7_pods_before.txt
( for i in $(seq 1 13); do date -u +%H:%M:%S; kubectl top pods -n app --no-headers; sleep 10; done ) > results/task7_top_pods.txt 2>&1 &
T=$!
.venv/bin/locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
  --host http://localhost:8080 --csv results/loadtest > results/task7_locust_stdout.txt 2>&1
echo "locust exit code: $?" >> results/task7_locust_stdout.txt
wait $T
kubectl -n app get pods -l app=parser -o wide > results/task7_pods_after.txt
tail -25 results/task7_locust_stdout.txt
cat results/task7_top_pods.txt
