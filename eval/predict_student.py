"""Generate predictions with a Pythia model (trained student or untrained base) for score.py.

  python eval/predict_student.py MODEL_DIR_OR_HF_NAME data/validation.jsonl OUT.jsonl [--max-new-tokens 48]

Greedy decoding with the same prompt format and output cut as the service
(training/common.py), so offline scores match what the deployed service returns.
"""
import argparse
import json
import os
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "training"))
from common import cut_output, prompt_for  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("gold")
    ap.add_argument("out")
    ap.add_argument("--max-new-tokens", type=int, default=48)
    a = ap.parse_args()
    torch.manual_seed(42)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model).eval()
    rows = [json.loads(ln) for ln in open(a.gold, encoding="utf-8") if ln.strip()]
    t0 = time.time()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f, torch.no_grad():
        for r in rows:
            enc = tok(prompt_for(r["text"]), return_tensors="pt")
            gen = model.generate(**enc, max_new_tokens=a.max_new_tokens, do_sample=False,
                                 pad_token_id=tok.eos_token_id, eos_token_id=tok.eos_token_id)
            text = tok.decode(gen[0, enc["input_ids"].shape[1]:], skip_special_tokens=True)
            f.write(json.dumps({"id": r["id"], "prediction": cut_output(text)}, ensure_ascii=False) + "\n")
    print(f"{len(rows)} predictions in {time.time() - t0:.1f}s -> {a.out}")


if __name__ == "__main__":
    main()
