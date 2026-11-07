"""Print a few examples of each rejection reason from the teacher shards (for the report)."""
import glob
import json
import sys

sys.path.insert(0, "worker")
from clean import check  # noqa: E402

ex = {}
for p in sorted(glob.glob("data/teacher/shard-*.jsonl")):
    for line in open(p, encoding="utf-8"):
        r = json.loads(line)
        reason, _ = check(r)
        if reason and len(ex.setdefault(reason, [])) < 3:
            ex[reason].append((r["id"], r["text"], r["teacher_raw"][:140]))
for k, v in ex.items():
    print(f"== {k}")
    for i, t, raw in v:
        print(f"  {i} | {t}\n      {raw!r}")
