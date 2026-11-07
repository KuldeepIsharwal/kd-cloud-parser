"""Run the teacher (phi3.5 on Ollama, temperature 0, seed 42, same prompt as Task 1) on a
labelled file and write raw replies for score.py.

  python eval/predict_teacher.py data/validation.jsonl results/teacher_validation_predictions.jsonl
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from worker import ask_teacher, build_prompt  # noqa: E402


def main():
    gold, out = sys.argv[1], sys.argv[2]
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    template = open("prompts/teacher_prompt.txt", encoding="utf-8").read()
    rows = [json.loads(ln) for ln in open(gold, encoding="utf-8") if ln.strip()]
    t0 = time.time()
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            raw = ask_teacher(url, "phi3.5", build_prompt(template, r["text"]))
            f.write(json.dumps({"id": r["id"], "prediction": raw}, ensure_ascii=False) + "\n")
    print(f"{len(rows)} teacher replies in {time.time() - t0:.1f}s -> {out}")


if __name__ == "__main__":
    main()
