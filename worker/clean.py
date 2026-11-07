"""Clean the teacher shard outputs into datasets/v1/train.jsonl (Task 1, step 6).

Usage
  python worker/clean.py --s3                      read s3://datasets/teacher/shard-*.jsonl, write
                                                   s3://datasets/v1/train.jsonl and train.sha256
  python worker/clean.py --in-dir DIR --out-dir OUT  same, on local files (DIR/shard-*.jsonl)

Rejection reasons, checked in this order for every record (the first failing one counts):
  (a) not_json      the reply is not valid JSON (or not a JSON object)
  (b) bad_keys      keys are not exactly intent, date, time, place
  (c) bad_intent    intent is not one of the eight
  (d) bad_slot      a slot is neither null nor a non-empty string that appears in the command
                    (case-insensitive substring match)
Then, among the records that passed (a)-(d):
  (e) duplicate     same command text (case and surrounding/multiple spaces ignored) as a record
                    with a smaller id; the smallest id is kept
Output records are sorted by id and look like
  {"id", "text", "teacher_raw", "target"}
where teacher_raw is the untouched teacher reply and target is the same JSON object
re-serialised compactly with json.dumps (keys in schema order). The file is written with
"\n" line endings and its SHA-256 is written to train.sha256 as "<hex>  train.jsonl".
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys

KEYS = ["intent", "date", "time", "place"]
INTENTS = {
    "alarm_set", "alarm_query", "calendar_set", "calendar_query",
    "calendar_remove", "weather_query", "datetime_query", "recommendation_events",
}
REASONS = ["not_json", "bad_keys", "bad_intent", "bad_slot"]


def norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def check(record):
    """Return (reason, None) for a rejected record, or (None, parsed_object) for a good one."""
    try:
        obj = json.loads(record["teacher_raw"])
    except (json.JSONDecodeError, TypeError):
        return "not_json", None
    if not isinstance(obj, dict):
        return "not_json", None
    if set(obj.keys()) != set(KEYS) or len(obj) != 4:
        return "bad_keys", None
    if obj["intent"] not in INTENTS:
        return "bad_intent", None
    text = norm(record["text"])
    for k in ("date", "time", "place"):
        v = obj[k]
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip() or norm(v) not in text:
            return "bad_slot", None
    return None, obj


def clean(records):
    """records: iterable of shard lines (dicts). Returns (kept_records, counts)."""
    counts = {"input": 0, **{r: 0 for r in REASONS}, "duplicate": 0, "kept": 0}
    valid = []
    for rec in records:
        counts["input"] += 1
        reason, obj = check(rec)
        if reason:
            counts[reason] += 1
        else:
            valid.append((rec, obj))
    valid.sort(key=lambda p: p[0]["id"])
    seen, kept = set(), []
    for rec, obj in valid:
        key = norm(rec["text"])
        if key in seen:
            counts["duplicate"] += 1
            continue
        seen.add(key)
        kept.append({
            "id": rec["id"],
            "text": rec["text"],
            "teacher_raw": rec["teacher_raw"],
            "target": json.dumps({k: obj[k] for k in KEYS}, ensure_ascii=False),
        })
    counts["kept"] = len(kept)
    return kept, counts


def serialise(kept):
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept).encode("utf-8")
    return data, hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--s3", action="store_true")
    ap.add_argument("--in-dir")
    ap.add_argument("--out-dir", default="build/dataset")
    ap.add_argument("--counts-out", default="results/clean_counts.json")
    a = ap.parse_args()

    lines = []
    if a.s3:
        import boto3
        if os.path.exists(".secrets/s3.env"):  # running on the laptop: credentials from the git-ignored file
            for line in open(".secrets/s3.env"):
                k, _, v = line.strip().partition("=")
                if k:
                    os.environ.setdefault(k, v)
        os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
        s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT", "http://localhost:8333"))
        keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket="datasets", Prefix="teacher/").get("Contents", []))
        for k in keys:
            lines += s3.get_object(Bucket="datasets", Key=k)["Body"].read().decode("utf-8").splitlines()
        print(f"read {len(keys)} shard objects: {keys}")
    elif a.in_dir:
        for p in sorted(glob.glob(os.path.join(a.in_dir, "shard-*.jsonl"))):
            lines += open(p, encoding="utf-8").read().splitlines()
    else:
        sys.exit("give --s3 or --in-dir")

    kept, counts = clean(json.loads(ln) for ln in lines if ln.strip())
    data, digest = serialise(kept)
    assert counts["input"] == sum(counts[r] for r in REASONS) + counts["duplicate"] + counts["kept"]

    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, "train.jsonl"), "wb").write(data)
    open(os.path.join(a.out_dir, "train.sha256"), "w").write(f"{digest}  train.jsonl\n")
    if a.s3:
        s3.put_object(Bucket="datasets", Key="v1/train.jsonl", Body=data)
        s3.put_object(Bucket="datasets", Key="v1/train.sha256", Body=f"{digest}  train.jsonl\n".encode())
        print("wrote s3://datasets/v1/train.jsonl and train.sha256")
    os.makedirs(os.path.dirname(a.counts_out) or ".", exist_ok=True)
    json.dump({**counts, "sha256": digest}, open(a.counts_out, "w"), indent=2)
    print(json.dumps(counts, indent=2))
    print("sha256", digest)


if __name__ == "__main__":
    main()
