"""Sequence-level knowledge distillation: fine-tune Pythia-70M on the teacher's replies (Task 2).

  python training/train.py [--config training/config.yaml] [--subset N]

Each example is
    Command: <the command>
    JSON: <the teacher's JSON reply><|endoftext|>
and the loss is computed only on the reply tokens (the prompt tokens are masked with -100).
Writes the model + tokenizer to output_dir, the per-epoch mean training loss to
training/loss.csv (training/loss_<version>.csv for other versions), a deterministic
tarball <output_dir>.tar.gz and model.sha256 (SHA-256 of the tarball and of every file).
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import random
import sys
import tarfile
import time

import numpy as np
import torch
import yaml
from transformers import AutoModelForCausalLM, AutoTokenizer, get_linear_schedule_with_warmup

sys.path.insert(0, os.path.dirname(__file__))
from common import prompt_for  # noqa: E402

SEED_DEFAULT = 42


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def load_records(path, limit):
    rows = [json.loads(ln) for ln in open(path, encoding="utf-8") if ln.strip()]
    return rows[:limit]


def encode(tok, rec, max_len, loss_on_prompt):
    p_ids = tok(prompt_for(rec["text"]))["input_ids"]
    a_ids = tok(" " + rec["target"])["input_ids"] + [tok.eos_token_id]
    ids = (p_ids + a_ids)[:max_len]
    labels = (p_ids if loss_on_prompt else [-100] * len(p_ids)) + a_ids
    return ids, labels[:max_len]


def batches(examples, bs, pad_id, rng):
    order = list(range(len(examples)))
    rng.shuffle(order)
    for i in range(0, len(order), bs):
        chunk = [examples[j] for j in order[i:i + bs]]
        width = max(len(ids) for ids, _ in chunk)
        ids = torch.full((len(chunk), width), pad_id)
        lab = torch.full((len(chunk), width), -100)
        att = torch.zeros((len(chunk), width), dtype=torch.long)
        for r, (x, y) in enumerate(chunk):
            ids[r, :len(x)] = torch.tensor(x)
            lab[r, :len(y)] = torch.tensor(y)
            att[r, :len(x)] = 1
        yield ids, att, lab


def deterministic_tar(src_dir, out_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name in sorted(os.listdir(src_dir)):
            p = os.path.join(src_dir, name)
            info = tar.gettarinfo(p, arcname=os.path.join(os.path.basename(src_dir), name))
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            with open(p, "rb") as f:
                tar.addfile(info, f)
    with open(out_path, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue())


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="training/config.yaml")
    ap.add_argument("--subset", type=int, default=0, help="train on the first N records only")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    seed = int(cfg.get("seed", SEED_DEFAULT))
    set_seed(seed)
    torch.set_num_threads(max(1, os.cpu_count() or 1))

    limit = min(cfg["max_train_records"], a.subset or cfg["max_train_records"])
    recs = load_records(cfg["train_file"], limit)
    out_dir = cfg["output_dir"] + (f"-subset{a.subset}" if a.subset else "")
    print(f"version {cfg['version']}: {len(recs)} records, seed {seed}, output {out_dir}", flush=True)

    tok = AutoTokenizer.from_pretrained(cfg["base_model"], revision=cfg["base_model_revision"])
    model = AutoModelForCausalLM.from_pretrained(cfg["base_model"], revision=cfg["base_model_revision"])
    pad_id = tok.eos_token_id
    examples = [encode(tok, r, cfg["max_seq_length"], cfg["loss_on_prompt"]) for r in recs]

    steps_per_epoch = (len(examples) + cfg["batch_size"] - 1) // cfg["batch_size"]
    total = steps_per_epoch * cfg["epochs"]
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    sched = get_linear_schedule_with_warmup(opt, int(cfg["warmup_ratio"] * total), total)
    rng = random.Random(seed)

    loss_rows = []
    model.train()
    t0 = time.time()
    for epoch in range(1, cfg["epochs"] + 1):
        losses = []
        for ids, att, lab in batches(examples, cfg["batch_size"], pad_id, rng):
            out = model(input_ids=ids, attention_mask=att, labels=lab)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            losses.append(out.loss.item())
        mean = sum(losses) / len(losses)
        loss_rows.append((epoch, round(mean, 6)))
        print(f"epoch {epoch}/{cfg['epochs']}  loss {mean:.4f}  ({time.time() - t0:.0f}s)", flush=True)

    loss_name = "loss.csv" if cfg["version"] == "v1" and not a.subset else (
        f"loss_{cfg['version']}{'_subset' + str(a.subset) if a.subset else ''}.csv")
    with open(os.path.join("training", loss_name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "train_loss"])
        w.writerows(loss_rows)

    os.makedirs(out_dir, exist_ok=True)
    model.save_pretrained(out_dir, safe_serialization=True)
    tok.save_pretrained(out_dir)
    json.dump({"version": cfg["version"], "base_model": cfg["base_model"], "seed": seed,
               "records": len(recs), "epochs": cfg["epochs"], "learning_rate": cfg["learning_rate"],
               "final_loss": loss_rows[-1][1], "train_seconds": round(time.time() - t0, 1)},
              open(os.path.join(out_dir, "version.json"), "w"), indent=2)

    name = os.path.basename(out_dir.rstrip("/"))
    parent = os.path.dirname(out_dir.rstrip("/"))
    tar_path = os.path.join(parent, f"pythia70m-kd-{name}.tar.gz")
    deterministic_tar(out_dir, tar_path)
    lines = [f"{sha256_file(tar_path)}  {os.path.basename(tar_path)}"]
    lines += [f"{sha256_file(os.path.join(out_dir, n))}  {n}" for n in sorted(os.listdir(out_dir))]
    open(os.path.join(parent, f"{name}.model.sha256"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"done in {time.time() - t0:.0f}s; loss written to training/{loss_name}")


if __name__ == "__main__":
    main()
