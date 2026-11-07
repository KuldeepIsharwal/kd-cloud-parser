# Knowledge distillation + local cloud deployment of a command parser.
# Run everything from the repository root on Linux/WSL with docker, k3d and kubectl installed.
#
#   make up                 cluster + SeaweedFS + buckets + dataset + model (from the GitHub Release) + service
#   make down               delete the cluster
#   make train [SUBSET=50]  fine-tune Pythia-70M from training/config.yaml
#   make test / make lint   unit tests / linting
#   make loadtest           the standard Locust run through the Ingress (http://localhost:8080)

SHELL        := /bin/bash
CLUSTER      := kdcloud
VENV         := .venv
PY           := $(VENV)/bin/python
CONFIG       ?= training/config.yaml
SUBSET       ?=
REPO         ?= KuldeepIsharwal/kd-cloud-parser
RELEASE_TAG  ?= model-v1
RELEASE_URL  := https://github.com/$(REPO)/releases/download/$(RELEASE_TAG)
IMAGE        := kd-parser:1.1
WORKER_IMAGE := kd-worker:1.0
export S3_ENDPOINT ?= http://localhost:8333

.PHONY: up down venv cluster storage secrets buckets dataset seed-models image deploy wait \
        labels clean-data train train-v2 publish-models eval test lint loadtest status

## ---------- one-command bring-up / tear-down ----------
up: venv cluster storage secrets buckets dataset seed-models image deploy wait
	@echo "Ready: curl -s -X POST localhost:8080/parse -H 'Content-Type: application/json' -d '{\"text\":\"what is the weather in london\"}'"

down:
	k3d cluster delete $(CLUSTER)

## ---------- pieces ----------
$(VENV)/.done: training/requirements.txt requirements-dev.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r training/requirements.txt -r requirements-dev.txt
	touch $@

venv: $(VENV)/.done

cluster:
	k3d cluster list $(CLUSTER) >/dev/null 2>&1 || k3d cluster create --config cluster/k3d.yaml

secrets:
	bash scripts/make_secrets.sh

storage: secrets
	kubectl apply -f k8s/data/seaweedfs.yaml
	bash scripts/make_secrets.sh
	kubectl -n data rollout status deploy/seaweedfs --timeout=300s
	@until $(PY) scripts/s3_tool.py ls >/dev/null 2>&1; do echo "waiting for S3..."; sleep 3; done

buckets:
	$(PY) scripts/s3_tool.py mb datasets models

dataset:
	$(PY) scripts/s3_tool.py put data/commands_pool.jsonl s3://datasets/commands_pool.jsonl
	for f in data/teacher/shard-*.jsonl; do \
	  $(PY) scripts/s3_tool.py put $$f s3://datasets/teacher/$$(basename $$f); done
	$(PY) scripts/s3_tool.py put data/v1/train.jsonl s3://datasets/v1/train.jsonl
	$(PY) scripts/s3_tool.py put data/v1/train.sha256 s3://datasets/v1/train.sha256

# Model files are not in Git: fetch the Release assets, verify checksums, upload to s3://models/models/vN/
seed-models:
	bash scripts/seed_models.sh "$(RELEASE_URL)" v1 v2

image:
	docker build -t $(IMAGE) -f service/Dockerfile .
	k3d image import $(IMAGE) -c $(CLUSTER)

deploy:
	kubectl apply -f k8s/app/parser.yaml

wait:
	kubectl -n app rollout status deploy/parser --timeout=600s
	@until curl -sf -o /dev/null -X POST localhost:8080/parse -H 'Content-Type: application/json' -d '{"text":"what time is it"}'; do sleep 2; done

status:
	kubectl get pods -A -o wide; kubectl -n app get hpa,ingress,svc,endpoints

## ---------- Task 1: teacher labelling ----------
labels:
	docker build -t $(WORKER_IMAGE) -f worker/Dockerfile .
	k3d image import $(WORKER_IMAGE) -c $(CLUSTER)
	kubectl create namespace pipeline --dry-run=client -o yaml | kubectl apply -f -
	bash scripts/teacher_endpoint.sh
	kubectl apply -f k8s/pipeline/workers.yaml
	kubectl -n pipeline wait --for=condition=complete job/teacher-labeller --timeout=24h

clean-data:
	$(PY) worker/clean.py --s3 --out-dir data/v1 --counts-out results/clean_counts.json

## ---------- Task 2: training ----------
train: venv
	$(PY) training/train.py --config $(CONFIG) $(if $(SUBSET),--subset $(SUBSET),)

train-v2: venv
	$(PY) training/train.py --config training/v2.yaml

publish-models:
	for v in v1 v2; do \
	  $(PY) scripts/s3_tool.py put-dir build/models/$$v s3://models/models/$$v && \
	  $(PY) scripts/s3_tool.py put build/models/pythia70m-kd-$$v.tar.gz s3://models/models/$$v/pythia70m-kd-$$v.tar.gz && \
	  $(PY) scripts/s3_tool.py put build/models/$$v.model.sha256 s3://models/models/$$v/model.sha256 || exit 1; done

eval: venv
	$(PY) eval/predict_student.py build/models/v1 data/validation.jsonl results/student_v1_validation_predictions.jsonl
	$(PY) tools/score.py results/student_v1_validation_predictions.jsonl data/validation.jsonl --out results/student_v1_validation.json

## ---------- Task 6 ----------
test: venv
	$(PY) -m pytest -q tests

lint: venv
	$(VENV)/bin/ruff check .

## ---------- Task 7 ----------
loadtest: venv
	mkdir -p results
	$(VENV)/bin/locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
	  --host http://localhost:8080 --csv results/loadtest || true
