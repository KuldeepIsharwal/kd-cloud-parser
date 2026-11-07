"""Print creation -> Ready seconds for every parser Pod (reads `kubectl get pods -o json` on stdin)."""
import json
import sys
from datetime import datetime


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


for p in json.load(sys.stdin)["items"]:
    ready = [c for c in p["status"]["conditions"] if c["type"] == "Ready"][0]
    secs = (ts(ready["lastTransitionTime"]) - ts(p["metadata"]["creationTimestamp"])).total_seconds()
    print(f"COLD {p['metadata']['name']} created={p['metadata']['creationTimestamp']} "
          f"ready={ready['lastTransitionTime']} seconds={secs:.0f}")
