# Knowledge Distillation + Local Cloud Deployment of a Command Parser

Cloud Computing (CS3081) mini project. Kuldeep Isharwal, roll number 230103038.

**GitHub repository:** https://github.com/KuldeepIsharwal/kd-cloud-parser
**Model release (weights, tokenizer, version info, checksums):** https://github.com/KuldeepIsharwal/kd-cloud-parser/releases/tag/model-v1
**Report:** [report/report.pdf](report/report.pdf)

Phi-3.5-mini (3.8B, Ollama, temperature 0, seed 42) labels 3,000 voice commands. Pythia-70M is
fine-tuned on those replies (sequence-level knowledge distillation). The student then runs as a
FastAPI service on a local k3d (k3s) cluster, and loads its weights from SeaweedFS object storage
at start-up.

```
cluster/k3d.yaml            k3d cluster definition (1 server node, ports 8080 -> Traefik, 8333 -> S3)
k8s/data/seaweedfs.yaml     SeaweedFS (S3 API) in namespace data
k8s/pipeline/workers.yaml   Indexed Job: 4 teacher-labelling workers (SHARD_INDEX / SHARD_COUNT)
k8s/app/parser.yaml         Deployment, Service, Ingress, HPA in namespace app
prompts/teacher_prompt.txt  teacher prompt
worker/                     worker.py (labelling), clean.py (filtering + checksum), Dockerfile
training/                   config.yaml, v2.yaml, train.py, common.py, loss.csv
eval/                       predict_student.py, predict_teacher.py
service/                    app.py (FastAPI), Dockerfile, requirements.txt (pinned)
network/                    subnets.md, nacl.json, check_subnets.py, packets_extra.jsonl
data/                       kit data + teacher shard outputs (data/teacher) + cleaned dataset (data/v1)
tests/                      unit tests (pytest)
tools/                      kit tools (score.py, locustfile.py, nacl_sim.py)
scripts/                    secrets, S3 helper, model seeding, experiment scripts for Task 3/4/7
results/                    every log, score report, Locust output and command output
.github/workflows/ci.yml    lint -> unit tests -> model evaluation (Release asset) -> quality gate; gitleaks
```

## Prerequisites
Linux or WSL2 (tested on Ubuntu 24.04 under WSL2 on Windows 11, 16 vCPU, 11 GB RAM for WSL).
You need Docker 24+, k3d 5.7, kubectl 1.31, GNU make, Python 3.12 with venv, and curl.
For relabelling only, you also need Ollama with `phi3.5`.

## Build and deploy (from a fresh clone, 3 commands)
```bash
git clone https://github.com/KuldeepIsharwal/kd-cloud-parser.git
cd kd-cloud-parser
make up
```
`make up` does the following:
1. Creates a venv.
2. Creates the k3d cluster from `cluster/k3d.yaml` and deploys SeaweedFS.
3. Generates random S3 credentials into `.secrets/` (git-ignored) and creates the Kubernetes Secrets.
4. Creates the `datasets` and `models` buckets and uploads the dataset files.
5. Downloads the v1 and v2 models from the GitHub Release, verifies their SHA-256, and uploads them to `s3://models/models/v1|v2/`.
6. Builds the service image and imports it into k3d.
7. Applies `k8s/app/parser.yaml` and waits until `/parse` answers through the Ingress.

```bash
curl -s -i -X POST localhost:8080/parse -H 'Content-Type: application/json' -d '{"text":"set an alarm for seven am tomorrow"}'
```

## Testing
```bash
make test        # unit tests
make lint        # ruff
make loadtest    # standard Locust run through the Ingress, results in results/loadtest_*
python3 tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check
```

## Reproducing the pipeline
```bash
docker run -d --name ollama -p 11434:11434 -e OLLAMA_NUM_PARALLEL=2 -v ollama:/root/.ollama ollama/ollama:0.5.4
docker exec ollama ollama pull phi3.5
make labels        # 4 parallel workers in namespace pipeline -> s3://datasets/teacher/shard-*.jsonl
make clean-data    # -> s3://datasets/v1/train.jsonl + train.sha256 (also data/v1/)
make train         # v1 from training/config.yaml  (make train SUBSET=50 for a quick check)
make train-v2      # v2 from training/v2.yaml
make publish-models
make eval
```
Checksum check: `python3 worker/clean.py --in-dir data/teacher --out-dir /tmp/c && diff /tmp/c/train.sha256 data/v1/train.sha256`

## Shutdown
```bash
make down                     # deletes the k3d cluster (and with it SeaweedFS and all Pods)
docker rm -f ollama           # optional: stop the teacher
```

## Results summary (measured; details in report/report.pdf and results/)
| | |
|---|---|
| Cleaning | 3,000 in: 129 not JSON, 5 bad keys, 3 bad intent, 250 bad slot, 39 duplicates, **2,574 kept** (train.sha256 reproducible) |
| Validation full-frame | teacher 41%, untrained Pythia 0%, **student v1 38%** (JSON validity 100%), v2 43% |
| Container at 1 CPU / 1 GiB | 50/50 OK, peak memory 568 MiB, p50 476 ms, image 1.34 GB, no weights inside |
| Kubernetes | cold start median 9 s; recovery 13 s with 0 failures; rolling update 0.32% failed; LB 50.2/49.8%; HPA 1-2-1 |
| Load test (standard) | 432 requests, 0% errors, p50 1,100 ms, p95 1,300 ms, 3.63 req/s |
| Cost | 0.605 INR per 1,000 requests (2 replicas x (1 vCPU + 1 GiB) = 7.90 INR/h) |
| CI | pass: https://github.com/KuldeepIsharwal/kd-cloud-parser/actions/runs/42349981408 / gate fail (untrained): https://github.com/KuldeepIsharwal/kd-cloud-parser/actions/runs/42350184923 |
