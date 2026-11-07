"""Teacher-labelling worker (Task 1).

Reads SHARD_INDEX and SHARD_COUNT from the environment, takes every command whose
0-based line number n satisfies n % SHARD_COUNT == SHARD_INDEX, sends it to the
teacher (phi3.5 on Ollama, temperature 0, seed 42) with prompts/teacher_prompt.txt,
and writes {"id", "text", "teacher_raw"} lines to s3://<bucket>/teacher/shard-<i>.jsonl.

The object is re-uploaded every FLUSH_EVERY records, and on start-up the worker
reads its own object back and skips ids it has already done, so a restarted Pod
resumes instead of starting over.

Environment
  SHARD_INDEX, SHARD_COUNT           sharding (required)
  OLLAMA_URL                         default http://host.k3d.internal:11434
  TEACHER_MODEL                      default phi3.5
  S3_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (from a Kubernetes Secret)
  DATASET_BUCKET                     default datasets
  INPUT_KEY                          default commands_pool.jsonl
  PROMPT_FILE                        default /app/prompts/teacher_prompt.txt
"""
import json
import os
import sys
import time
import urllib.request

TEMPERATURE = 0
SEED = 42


def shard_lines(lines, index, count):
    """Return the lines whose 0-based position leaves remainder `index` mod `count`."""
    if count < 1 or not 0 <= index < count:
        raise ValueError(f"bad shard {index}/{count}")
    return [line for n, line in enumerate(lines) if n % count == index]


def build_prompt(template, command):
    return template.replace("{command}", command)


def ask_teacher(url, model, prompt, timeout=600):
    """One non-streaming call to Ollama; returns the reply text exactly as generated."""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        # The reply is one line of JSON; phi3.5 otherwise keeps writing an explanation
        # after it, so generation stops at the first newline. The reply is stored as is.
        "options": {"temperature": TEMPERATURE, "seed": SEED, "num_predict": 128, "num_ctx": 1024,
                    "stop": ["\n"]},
    }).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["response"]
        except Exception as e:  # network hiccup: back off and retry
            print(f"teacher call failed ({e}), retry {attempt + 1}", flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("teacher unreachable")


def main():
    import boto3  # imported here so the pure helpers above can be unit-tested without boto3

    index = int(os.environ["SHARD_INDEX"])
    count = int(os.environ["SHARD_COUNT"])
    url = os.environ.get("OLLAMA_URL", "http://host.k3d.internal:11434")
    model = os.environ.get("TEACHER_MODEL", "phi3.5")
    bucket = os.environ.get("DATASET_BUCKET", "datasets")
    in_key = os.environ.get("INPUT_KEY", "commands_pool.jsonl")
    out_key = f"teacher/shard-{index}.jsonl"
    flush_every = int(os.environ.get("FLUSH_EVERY", "25"))
    template = open(os.environ.get("PROMPT_FILE", "/app/prompts/teacher_prompt.txt"), encoding="utf-8").read()

    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"])
    lines = s3.get_object(Bucket=bucket, Key=in_key)["Body"].read().decode().splitlines()
    lines = [ln for ln in lines if ln.strip()]
    mine = [json.loads(ln) for ln in shard_lines(lines, index, count)]

    done = []
    try:
        done = s3.get_object(Bucket=bucket, Key=out_key)["Body"].read().decode().splitlines()
        done = [ln for ln in done if ln.strip()]
    except s3.exceptions.NoSuchKey:
        pass
    done_ids = {json.loads(ln)["id"] for ln in done}
    print(f"shard {index}/{count}: {len(mine)} commands, {len(done_ids)} already done", flush=True)

    def flush():
        s3.put_object(Bucket=bucket, Key=out_key, Body=("\n".join(done) + "\n").encode())

    t0 = time.time()
    new = 0
    for rec in mine:
        if rec["id"] in done_ids:
            continue
        raw = ask_teacher(url, model, build_prompt(template, rec["text"]))
        done.append(json.dumps({"id": rec["id"], "text": rec["text"], "teacher_raw": raw}, ensure_ascii=False))
        new += 1
        if new % flush_every == 0:
            flush()
            rate = new / (time.time() - t0)
            print(f"shard {index}: {len(done)}/{len(mine)} ({rate:.2f} cmd/s)", flush=True)
    flush()
    print(f"shard {index}: finished, {len(done)} records in s3://{bucket}/{out_key}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
