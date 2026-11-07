"""Command-parser inference service (Task 3).

Endpoints
  POST /parse    {"text": "..."} -> 200 + the four-key JSON object (and nothing else),
                 headers X-Model-Version and X-Served-By; 500 {"error": "invalid_model_output"}
                 when the model output does not satisfy schema.json
  GET  /healthz  200 while the process is alive
  GET  /readyz   503 until the model is loaded, then 200

Configuration (environment only)
  MODEL_URI       s3://bucket/prefix of the model + tokenizer files, e.g. s3://models/models/v1
  MODEL_VERSION   reported in X-Model-Version, e.g. v1
  S3_ENDPOINT     e.g. http://seaweedfs-s3.data.svc.cluster.local:8333
  MAX_NEW_TOKENS  generation budget, e.g. 48
  FAULT_INJECT    "1" replaces the model output with "not json" before validation
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY   from a Kubernetes Secret
  POD_NAME        reported in X-Served-By (falls back to the hostname)
"""
import json
import logging
import os
import socket
import tempfile
import threading
import time

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parser")

MODEL_URI = os.environ.get("MODEL_URI", "")
MODEL_VERSION = os.environ.get("MODEL_VERSION", "unknown")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "48"))
FAULT_INJECT = os.environ.get("FAULT_INJECT", "0") == "1"
SERVED_BY = os.environ.get("POD_NAME") or socket.gethostname()
SCHEMA_PATH = os.environ.get("SCHEMA_PATH", os.path.join(os.path.dirname(__file__), "schema.json"))

SCHEMA = json.load(open(SCHEMA_PATH, encoding="utf-8"))
KEYS = SCHEMA["keys"]
INTENTS = set(SCHEMA["intents"])

state = {"ready": False, "model": None, "tok": None, "error": None}
gen_lock = threading.Lock()
app = FastAPI(title="command-parser")


class ParseRequest(BaseModel):
    text: str


def prompt_for(command):
    return f"Command: {command}\nJSON:"


def cut_output(text):
    return text.strip().split("\n", 1)[0].strip()


def validate(raw):
    """Return the parsed object if raw satisfies schema.json, else None."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict) or set(obj) != set(KEYS) or len(obj) != len(KEYS):
        return None
    if obj["intent"] not in INTENTS:
        return None
    if not all(obj[k] is None or isinstance(obj[k], str) for k in KEYS if k != "intent"):
        return None
    return {k: obj[k] for k in KEYS}


def download_model(dest):
    import boto3
    bucket, _, prefix = MODEL_URI[len("s3://"):].partition("/")
    prefix = prefix.rstrip("/") + "/"
    s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT)
    objs = s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
    if not objs:
        raise RuntimeError(f"no objects under {MODEL_URI}")
    total = 0
    for o in objs:
        rel = o["Key"][len(prefix):]
        if "/" in rel or rel.endswith(".tar.gz"):
            continue  # only the flat model + tokenizer files
        s3.download_file(bucket, o["Key"], os.path.join(dest, rel))
        total += o["Size"]
        log.info("downloaded s3://%s/%s (%d bytes)", bucket, o["Key"], o["Size"])
    return total


def load_model():
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "1")))
        t0 = time.time()
        dest = tempfile.mkdtemp(prefix="model-")
        log.info("model download start: %s from %s (version %s)", MODEL_URI, S3_ENDPOINT, MODEL_VERSION)
        size = download_model(dest)
        log.info("model download done: %d bytes in %.2fs", size, time.time() - t0)
        state["tok"] = AutoTokenizer.from_pretrained(dest)
        state["model"] = AutoModelForCausalLM.from_pretrained(dest).eval()
        state["ready"] = True
        log.info("model loaded and ready after %.2fs", time.time() - t0)
    except Exception as e:  # stay not-ready; liveness keeps passing so the error is visible in logs
        state["error"] = repr(e)
        log.exception("model load failed")


def generate(text):
    import torch
    tok, model = state["tok"], state["model"]
    enc = tok(prompt_for(text), return_tensors="pt")
    with gen_lock, torch.no_grad():
        out = model.generate(**enc, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
                             pad_token_id=tok.eos_token_id, eos_token_id=tok.eos_token_id)
    return cut_output(tok.decode(out[0, enc["input_ids"].shape[1]:], skip_special_tokens=True))


@app.on_event("startup")
def startup():
    if os.environ.get("SKIP_MODEL_LOAD") != "1":
        threading.Thread(target=load_model, daemon=True).start()


def headers():
    return {"X-Model-Version": MODEL_VERSION, "X-Served-By": SERVED_BY}


@app.get("/healthz")
def healthz():
    return Response(content="ok", media_type="text/plain")


@app.get("/readyz")
def readyz():
    if state["ready"]:
        return Response(content="ready", media_type="text/plain")
    return Response(content="loading", status_code=503, media_type="text/plain")


@app.post("/parse")
async def parse(req: ParseRequest):
    if not state["ready"]:
        return JSONResponse({"error": "model_not_ready"}, status_code=503, headers=headers())
    raw = await run_in_threadpool(generate, req.text)
    if FAULT_INJECT:
        raw = "not json"
    obj = validate(raw)
    if obj is None:
        log.warning("invalid model output for %r: %r", req.text, raw)
        return JSONResponse({"error": "invalid_model_output"}, status_code=500, headers=headers())
    return JSONResponse(obj, status_code=200, headers=headers())
