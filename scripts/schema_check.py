"""Count predictions that pass the service's full schema check (known intent included)."""
import json
import sys

sys.path.insert(0, "training")
from common import INTENTS, is_valid  # noqa: E402

for path in sys.argv[1:]:
    rows = [json.loads(x) for x in open(path, encoding="utf-8")]
    bad = [r for r in rows if not is_valid(r["prediction"], set(INTENTS))]
    print(f"{path}: {len(rows) - len(bad)}/{len(rows)} pass the service schema check")
    for r in bad:
        print("   ", r["id"], r["prediction"][:110])
