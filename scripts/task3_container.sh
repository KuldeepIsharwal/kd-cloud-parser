#!/usr/bin/env bash
# Task 3 evidence: run the service image alone in Docker with 1 CPU / 1 GiB, check the API,
# send 50 sequential requests, record peak memory, and test FAULT_INJECT=1.
# Output: results/task3_*.txt
set -uo pipefail
cd "$(dirname "$0")/.."
source .secrets/s3.env
IMAGE=${IMAGE:-kd-parser:1.0}
OUT=results
mkdir -p $OUT
common=(--network host -e MODEL_URI=s3://models/models/v1 -e MODEL_VERSION=v1
        -e S3_ENDPOINT=http://localhost:8333 -e MAX_NEW_TOKENS=48 -e AWS_DEFAULT_REGION=us-east-1
        -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY")

{
echo "### image size and weight check"
docker image ls "$IMAGE"
docker image inspect "$IMAGE" --format 'uncompressed size: {{.Size}} bytes'
echo "model weight files inside the image (expect none):"
docker run --rm --entrypoint sh "$IMAGE" -c 'find / -xdev \( -name "*.safetensors" -o -name "pytorch_model*.bin" \) 2>/dev/null | wc -l'
} 2>&1 | tee $OUT/task3_image.txt

docker rm -f parser-limits >/dev/null 2>&1
docker run -d --name parser-limits --cpus 1 --memory 1g -e PORT=8000 -e POD_NAME=parser-limits \
  -e FAULT_INJECT=0 "${common[@]}" "$IMAGE" >/dev/null
{
echo "### docker run --cpus 1 --memory 1g (container parser-limits)"
docker inspect parser-limits --format 'NanoCpus={{.HostConfig.NanoCpus}} Memory={{.HostConfig.Memory}}'
echo "readyz while loading:"; curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/readyz
until [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz)" = 200 ]; do sleep 0.5; done
echo "readyz after load: $(curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz)"
echo "healthz: $(curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz)"
echo "--- container log (model download from object storage) ---"
docker logs parser-limits 2>&1 | grep -E "download|ready" | head -20
echo "--- one request with headers ---"
curl -s -i -X POST localhost:8000/parse -H 'Content-Type: application/json' -d '{"text":"set an alarm for seven thirty am tomorrow"}'
echo
} 2>&1 | tee $OUT/task3_api.txt

# memory sampler: docker stats every ~0.5 s while the 50 requests run
( while docker inspect parser-limits >/dev/null 2>&1; do
    docker stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}}' parser-limits; done ) > $OUT/task3_memory_samples.txt &
SAMPLER=$!
{
echo "### 50 sequential requests"
python3 - <<'EOF'
import json, time, urllib.request
texts = [json.loads(l)["text"] for l in open("data/validation.jsonl")][:50]
codes, lat = {}, []
for t in texts:
    req = urllib.request.Request("http://localhost:8000/parse", data=json.dumps({"text": t}).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            c = r.status; r.read()
    except urllib.error.HTTPError as e:
        c = e.code
    lat.append(time.time() - t0); codes[c] = codes.get(c, 0) + 1
lat.sort()
print("status codes:", codes)
print(f"latency mean {sum(lat)/len(lat)*1000:.0f} ms, p50 {lat[24]*1000:.0f} ms, max {lat[-1]*1000:.0f} ms")
EOF
} 2>&1 | tee $OUT/task3_50_requests.txt
kill $SAMPLER 2>/dev/null; sleep 1
{
echo "### memory (docker stats samples during the 50 requests)"
wc -l < $OUT/task3_memory_samples.txt | sed 's/^/samples: /'
python3 - <<'EOF'
import re
vals = []
for line in open("results/task3_memory_samples.txt"):
    m = re.match(r"([\d.]+)(KiB|MiB|GiB)", line)
    if m:
        v = float(m.group(1)) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[m.group(2)]
        vals.append(v)
print(f"peak memory: {max(vals):.1f} MiB of 1024 MiB limit; min {min(vals):.1f} MiB")
EOF
echo "OOMKilled: $(docker inspect parser-limits --format '{{.State.OOMKilled}}')  restarts: $(docker inspect parser-limits --format '{{.RestartCount}}')  status: $(docker inspect parser-limits --format '{{.State.Status}}')"
} 2>&1 | tee $OUT/task3_peak_memory.txt
docker rm -f parser-limits >/dev/null

# fault injection
docker run -d --name parser-fault --cpus 1 --memory 1g -e POD_NAME=parser-fault -e FAULT_INJECT=1 "${common[@]}" "$IMAGE" >/dev/null
until [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz)" = 200 ]; do sleep 0.5; done
{
echo "### FAULT_INJECT=1"
curl -s -i -X POST localhost:8000/parse -H 'Content-Type: application/json' -d '{"text":"what is the weather in london"}'
echo
} 2>&1 | tee $OUT/task3_fault_inject.txt
docker rm -f parser-fault >/dev/null
