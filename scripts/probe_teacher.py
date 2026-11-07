"""Quick smoke test of the teacher prompt on the first N validation commands (timing + raw replies)."""
import json
import os
import sys
import time

sys.path.insert(0, "worker")
from worker import ask_teacher, build_prompt  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
tpl = open("prompts/teacher_prompt.txt").read()
rows = [json.loads(x) for x in open("data/validation.jsonl")][:n]
for r in rows:
    t = time.time()
    raw = ask_teacher(os.environ.get("OLLAMA_URL", "http://localhost:11434"), "phi3.5", build_prompt(tpl, r["text"]))
    gold = {k: r[k] for k in ("intent", "date", "time", "place")}
    print(f"{time.time() - t:5.1f}s | {r['text']}\n   raw : {raw!r}\n   gold: {json.dumps(gold)}")
