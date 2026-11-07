# AI use

## Tools used
- **Claude Code (Anthropic, Claude Opus model)**, run as a coding agent on my laptop (WSL2 Ubuntu).

## What it was used for
- Reading the assignment handout and the student kit, and planning the repository layout.
- Drafting code: the labelling worker and `clean.py`, the training script, the FastAPI service,
  the Dockerfiles, the Kubernetes manifests, the Makefile, the GitHub Actions workflow and the unit tests.
- Installing the toolchain in WSL (Docker, k3d, kubectl; Ollama as a container) and running the
  commands for every task. Every number in the report comes from a command it ran on my machine; the
  raw outputs are in `results/`.
- Drafting the report text and the subnet working.

## How I checked what it gave me
- **Teacher prompt:** tested on validation commands before the full run. That showed phi3.5 kept
  writing an explanation after the JSON, so generation now stops at the first newline.
- **Sharding and cleaning:** unit tests (`tests/test_worker_clean.py`) check that every line lands
  in exactly one shard, check each rejection reason, and check that the output is deterministic.
  `clean.py` asserts that input = (a)+(b)+(c)+(d)+duplicates+kept, and re-running it on the stored
  shards reproduces `train.sha256`.
- **Subnets and NACL:** recomputed with Python's `ipaddress` module (`network/check_subnets.py`),
  checked with the kit's `nacl_sim.py` on the 6 sample packets plus 15 extra edge-case packets
  (`network/packets_extra.jsonl`).
- **Service:** tests with a fake model cover the headers, `FAULT_INJECT`, invalid outputs and
  readiness. I also checked it by hand with curl in Docker and through the Ingress.
- **Results:** all scores come from the kit's `score.py`, and all load numbers from the kit's
  `locustfile.py`. Every value in the report was checked against the files in `results/`.
- **Problems the AI ran into and fixed, which I reviewed:**
  - WSL ran out of memory with 4 parallel teacher contexts. Fixed by raising the WSL memory limit
    and using 2 Ollama slots with a 1024-token context.
  - `host.k3d.internal` disappeared after a cluster restart. Replaced it with a selector-less
    Service/Endpoints for the teacher.
