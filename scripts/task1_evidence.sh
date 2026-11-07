#!/usr/bin/env bash
# Task 1 evidence: cluster, SeaweedFS, buckets, worker Pods, shard coverage, cleaning counts.
set -uo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
R=results; mkdir -p $R data/teacher data/v1
until kubectl get nodes >/dev/null 2>&1; do sleep 2; done
kubectl -n data rollout status deploy/seaweedfs --timeout=300s >/dev/null
until python scripts/s3_tool.py ls >/dev/null 2>&1; do sleep 2; done
{
echo "### k3d cluster"; k3d cluster list; kubectl get nodes -o wide
echo; echo "### namespace data"; kubectl -n data get deploy,pods,svc,pvc
echo; echo "### buckets"; python scripts/s3_tool.py ls
echo; echo "### s3://datasets"; python scripts/s3_tool.py ls s3://datasets/
echo; echo "### worker job in namespace pipeline"; kubectl -n pipeline get job teacher-labeller -o wide
kubectl -n pipeline get pods -L batch.kubernetes.io/job-completion-index -o wide
for p in $(kubectl -n pipeline get pods -o name); do
  echo "--- $p SHARD_INDEX=$(kubectl -n pipeline get $p -o jsonpath='{.metadata.annotations.batch\.kubernetes\.io/job-completion-index}')"
  kubectl -n pipeline logs $p | sed -n '1p;$p'
done
} 2>&1 | tee $R/task1_cluster_storage.txt

for i in 0 1 2 3; do python scripts/s3_tool.py get s3://datasets/teacher/shard-$i.jsonl data/teacher/shard-$i.jsonl >/dev/null; done
python - <<'EOF' | tee $R/task1_shard_coverage.txt
import json, glob, collections
pool = [json.loads(l)["id"] for l in open("data/commands_pool.jsonl") if l.strip()]
seen = collections.Counter()
for p in sorted(glob.glob("data/teacher/shard-*.jsonl")):
    ids = [json.loads(l)["id"] for l in open(p) if l.strip()]
    idx = int(p.split("-")[-1].split(".")[0])
    expected = [x for n, x in enumerate(pool) if n % 4 == idx]
    print(f"{p}: {len(ids)} records, matches line%4=={idx}: {sorted(ids) == sorted(expected)}")
    seen.update(ids)
missing = [i for i in pool if seen[i] == 0]
repeats = [i for i, c in seen.items() if c > 1]
print(f"pool ids: {len(pool)}, ids in shards: {sum(seen.values())}, missing: {len(missing)}, repeated: {len(repeats)}")
EOF
python worker/clean.py --s3 --out-dir data/v1 --counts-out $R/clean_counts.json 2>&1 | tee $R/task1_clean_output.txt
echo "### reproducibility: re-run clean.py on the local copies of the shards" | tee $R/task1_checksum_check.txt
python worker/clean.py --in-dir data/teacher --out-dir /tmp/clean_check --counts-out /tmp/clean_check/counts.json >/dev/null
{ cat data/v1/train.sha256; cat /tmp/clean_check/train.sha256; python scripts/s3_tool.py get s3://datasets/v1/train.sha256 /tmp/s3sha >/dev/null; cat /tmp/s3sha
  cmp -s data/v1/train.sha256 /tmp/clean_check/train.sha256 && echo "MATCH" || echo "MISMATCH"; } | tee -a $R/task1_checksum_check.txt
