"""Generate predictions with a Pythia model (trained student or untrained base) for score.py.

  python eval/predict_student.py MODEL_DIR_OR_HF_NAME data/validation.jsonl OUT.jsonl
         [--max-new-tokens 48] [--decoding constrained|greedy]

Uses exactly the decoding code of the service (training/common.py): by default
schema-constrained decoding (intent chosen among the eight allowed values, slots greedy);
--decoding greedy gives plain greedy decoding for comparison.
"""
import argparse
import json
import os
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "training"))
from common import constrained_generate, greedy_generate  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("gold")
    ap.add_argument("out")
    ap.add_argument("--max-new-tokens", type=int, default=48)
    ap.add_argument("--decoding", choices=["constrained", "greedy"], default="constrained")
    a = ap.parse_args()
    torch.manual_seed(42)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model).eval()
    gen = constrained_generate if a.decoding == "constrained" else greedy_generate
    rows = [json.loads(ln) for ln in open(a.gold, encoding="utf-8") if ln.strip()]
    t0 = time.time()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            pred = gen(model, tok, r["text"], a.max_new_tokens)
            f.write(json.dumps({"id": r["id"], "prediction": pred}, ensure_ascii=False) + "\n")
    print(f"{len(rows)} predictions ({a.decoding}) in {time.time() - t0:.1f}s -> {a.out}")


if __name__ == "__main__":
    main()
