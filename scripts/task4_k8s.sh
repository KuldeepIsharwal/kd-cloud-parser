#!/usr/bin/env bash
# Task 4 experiments. Usage: scripts/task4_k8s.sh <step>
#   basics | readiness | hpa | rolling | recovery | coldstart | lb | all
# Every step writes its evidence to results/task4_<step>*.
set -uo pipefail
cd "$(dirname "$0")/.."
R=results; mkdir -p $R
LOCUST=".venv/bin/locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --host http://localhost:8080"
ts() { date -u +%H:%M:%S; }

wait_ready() { kubectl -n app rollout status deploy/parser --timeout=600s; }

basics() {
  {
  echo "### kubectl get (namespace app)"; kubectl -n app get deploy,rs,pods,svc,ingress,hpa,endpoints -o wide
  echo; echo "### resources and probes"; kubectl -n app get deploy parser -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}{.spec.template.spec.containers[0].livenessProbe}{"\n"}{.spec.template.spec.containers[0].readinessProbe}{"\n"}'
  echo; echo "### POST /parse through the Ingress (localhost:8080 -> Traefik -> Service parser)"
  curl -s -i -X POST localhost:8080/parse -H 'Content-Type: application/json' -d '{"text":"what is the weather in london"}'; echo
  } 2>&1 | tee $R/task4_basics.txt
}

readiness() {
  # Scale to 0, then to 1, and watch the Service endpoints once per second while the model loads.
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":1,"maxReplicas":1}}' >/dev/null
  kubectl -n app scale deploy/parser --replicas=0; kubectl -n app wait --for=delete pod -l app=parser --timeout=120s
  kubectl -n app scale deploy/parser --replicas=1
  {
  echo "### $(ts) scaled 0 -> 1; endpoints of Service parser every second"
  for i in $(seq 1 60); do
    ready=$(kubectl -n app get endpoints parser -o jsonpath='{.subsets[*].addresses[*].ip}')
    notready=$(kubectl -n app get endpoints parser -o jsonpath='{.subsets[*].notReadyAddresses[*].ip}')
    rz=$(kubectl -n app get pods -l app=parser -o jsonpath='{.items[0].status.containerStatuses[0].ready}')
    echo "$(ts) ready=[${ready}] notReady=[${notready}] podReady=${rz}"
    [ -n "$ready" ] && break; sleep 1
  done
  echo "--- pod log ---"; kubectl -n app logs -l app=parser --tail 20 | grep -E "download|ready"
  } 2>&1 | tee $R/task4_readiness.txt
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":1,"maxReplicas":2}}' >/dev/null
}

hpa() {
  # HPA min 1 / max 2 / 70% CPU. Start from 1 replica, load for 4 minutes, then watch it scale back down.
  kubectl -n app scale deploy/parser --replicas=1; wait_ready
  ( for i in $(seq 1 66); do echo "$(ts) $(kubectl -n app get hpa parser -o jsonpath='cpu={.status.currentMetrics[0].resource.current.averageUtilization}%/70% currentReplicas={.status.currentReplicas} desiredReplicas={.status.desiredReplicas}') pods=$(kubectl -n app get pods -l app=parser --no-headers | wc -l)"; sleep 10; done ) > $R/task4_hpa_watch.txt &
  W=$!
  sleep 20
  LOADTEST_HEADERS_OUT=$R/task4_hpa_headers.json $LOCUST --run-time 4m --csv $R/task4_hpa > $R/task4_hpa_locust.txt 2>&1
  wait $W
  kubectl -n app describe hpa parser | sed -n '/Events/,$p' > $R/task4_hpa_events.txt
  cat $R/task4_hpa_watch.txt $R/task4_hpa_events.txt
}

rolling() {
  kubectl -n app scale deploy/parser --replicas=2; wait_ready
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":2,"maxReplicas":2}}' >/dev/null
  LOADTEST_HEADERS_OUT=$R/task4_rolling_headers.json $LOCUST --run-time 5m --csv $R/task4_rolling > $R/task4_rolling_locust.txt 2>&1 &
  L=$!
  {
  sleep 30
  echo "$(ts) set MODEL_VERSION=v2 MODEL_URI=s3://models/models/v2"
  kubectl -n app set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/models/v2
  wait_ready; echo "$(ts) rollout to v2 complete"
  for i in 1 2 3; do curl -s -D - -o /dev/null -X POST localhost:8080/parse -H 'Content-Type: application/json' -d '{"text":"what time is it"}' | grep -i x-model-version; done
  sleep 45
  echo "$(ts) kubectl rollout undo"
  kubectl -n app rollout undo deploy/parser
  wait_ready; echo "$(ts) rollback complete"
  kubectl -n app rollout history deploy/parser
  } 2>&1 | tee $R/task4_rolling_steps.txt
  wait $L
  {
  echo "### after rollback: X-Model-Version of 5 requests"
  for i in 1 2 3 4 5; do curl -s -D - -o /dev/null -X POST localhost:8080/parse -H 'Content-Type: application/json' -d '{"text":"what is the weather in paris"}' | grep -iE "x-model-version|x-served-by" | tr -d '\r' | paste -sd' '; done
  echo "### locust totals"; grep -E "Aggregated|/parse" $R/task4_rolling_stats.csv
  echo "### per model version"; cat $R/task4_rolling_headers.json
  } 2>&1 | tee $R/task4_rolling_result.txt
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":1,"maxReplicas":2}}' >/dev/null
}

recovery() {
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":2,"maxReplicas":2}}' >/dev/null
  kubectl -n app scale deploy/parser --replicas=2; wait_ready
  LOADTEST_HEADERS_OUT=$R/task4_recovery_headers.json $LOCUST --run-time 3m --csv $R/task4_recovery > $R/task4_recovery_locust.txt 2>&1 &
  L=$!
  {
  sleep 40
  victim=$(kubectl -n app get pods -l app=parser -o jsonpath='{.items[0].metadata.name}')
  echo "$(ts) deleting pod $victim"; kubectl -n app delete pod "$victim" --wait=false
  for i in $(seq 1 40); do echo "$(ts) $(kubectl -n app get deploy parser --no-headers | awk '{print "ready="$2" up-to-date="$3" available="$4}')"; sleep 3; done
  kubectl -n app get pods -o wide
  } 2>&1 | tee $R/task4_recovery_watch.txt
  wait $L
  grep -E "Aggregated" $R/task4_recovery_stats.csv | tee -a $R/task4_recovery_watch.txt
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":1,"maxReplicas":2}}' >/dev/null
}

coldstart() {
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":2,"maxReplicas":2}}' >/dev/null
  kubectl -n app scale deploy/parser --replicas=2; wait_ready
  : > $R/task4_coldstart.txt
  for run in 1 2 3; do
    echo "### run $run: $(ts) delete all parser pods" | tee -a $R/task4_coldstart.txt
    kubectl -n app delete pods -l app=parser --wait=false >/dev/null
    sleep 3; wait_ready >/dev/null
    until [ "$(kubectl -n app get pods -l app=parser --field-selector=status.phase=Running -o jsonpath='{range .items[*]}{.status.containerStatuses[0].ready}{"\n"}{end}' | grep -c true)" -ge 2 ] \
       && [ "$(kubectl -n app get pods -l app=parser --no-headers | wc -l)" -eq 2 ]; do sleep 1; done
    kubectl -n app get pods -l app=parser -o json | python3 scripts/coldstart_times.py | tee -a $R/task4_coldstart.txt
    for p in $(kubectl -n app get pods -l app=parser -o name); do
      echo "--- log $p"; kubectl -n app logs "$p" | grep -E "download|ready after"; done >> $R/task4_coldstart.txt
  done
  python3 - <<'EOF' | tee -a $R/task4_coldstart.txt
import re, statistics
runs, cur = [], []
for line in open("results/task4_coldstart.txt"):
    if line.startswith("### run"):
        if cur: runs.append(cur)
        cur = []
    m = re.search(r"COLD .* seconds=(\d+)", line)
    if m: cur.append(int(m.group(1)))
runs.append(cur)
per_run = [max(r) for r in runs]
print("per-run cold start (slowest pod, creation -> Ready):", per_run, "s")
print("median over 3 runs:", statistics.median(per_run), "s")
EOF
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":1,"maxReplicas":2}}' >/dev/null
}

lb() {
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":2,"maxReplicas":2}}' >/dev/null
  kubectl -n app scale deploy/parser --replicas=2; wait_ready
  kubectl -n app get pods -l app=parser -o wide | tee $R/task4_lb_pods.txt
  LOADTEST_HEADERS_OUT=$R/task4_lb_headers.json $LOCUST --run-time 2m --csv $R/task4_lb 2>&1 | tail -30 > $R/task4_lb_locust.txt
  python3 -c '
import json
h = json.load(open("results/task4_lb_headers.json"))["per_replica"]
t = sum(h.values())
for k, v in h.items(): print(f"{k}: {v} requests = {100*v/t:.1f}%")
print("total successful:", t)' | tee $R/task4_lb_result.txt
  kubectl -n app patch hpa parser --type merge -p '{"spec":{"minReplicas":1,"maxReplicas":2}}' >/dev/null
}

case "${1:-all}" in
  all) basics; readiness; hpa; rolling; recovery; coldstart; lb ;;
  *) "$1" ;;
esac
