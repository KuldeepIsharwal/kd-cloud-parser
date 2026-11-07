"""Task 7: cost per 1,000 requests (rate_card.json) and SLO error budget, from results/loadtest_stats.csv."""
import csv
import json

rate = json.load(open("data/rate_card.json"))
row = [r for r in csv.DictReader(open("results/loadtest_stats.csv")) if r["Name"] == "Aggregated"][0]
reqs, fails = int(row["Request Count"]), int(row["Failure Count"])
rps = float(row["Requests/s"])
p50, p95 = row["50%"], row["95%"]

replicas, cpu_limit, mem_limit_gib = 2, 1.0, 1.0   # from k8s/app/parser.yaml during the run
per_replica = cpu_limit * rate["vcpu_hour"] + mem_limit_gib * rate["gib_memory_hour"]
hourly = replicas * per_replica
per_hour = rps * 3600
cost_1000 = hourly / per_hour * 1000

print("== Measured (results/loadtest_stats.csv, standard run: 4 users, 2 min, through the Ingress)")
print(f"requests={reqs} failures={fails} error_rate={100 * fails / reqs:.2f}%")
print(f"p50={p50} ms p95={p95} ms throughput={rps:.3f} req/s")
print("\n== Cost (rates from data/rate_card.json, currency INR; replica billed for its limits)")
print(f"per replica: {cpu_limit} vCPU x {rate['vcpu_hour']} + {mem_limit_gib} GiB x {rate['gib_memory_hour']}"
      f" = {per_replica:.2f} INR/h")
print(f"all replicas: {replicas} x {per_replica:.2f} = {hourly:.2f} INR/h")
print(f"requests served per hour: {rps:.4f} req/s x 3600 = {per_hour:.1f}")
print(f"cost per 1,000 requests = {hourly:.2f} / {per_hour:.1f} x 1000 = {cost_1000:.4f} INR")

target = 0.99
budget = (1 - target) * reqs
print("\n== SLO: 99% of /parse requests return HTTP 200 within 30 s, window = one standard load-test run")
print(f"error budget = (1 - 0.99) x {reqs} = {budget:.2f} -> {int(budget)} failed requests allowed")
print(f"used: {fails} failed requests = {100 * fails / budget:.1f}% of the budget; SLO met: {fails <= budget}")
