import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "network"))

from check_subnets import plan  # noqa: E402


def test_subnet_plan():
    rows = {r[0]: r for r in plan()}
    assert rows["app"][1:3] == ("10.20.0.0", 22)
    assert rows["public"][1:3] == ("10.20.4.0", 24)
    assert rows["data"][4] == "10.20.5.127"
    assert rows["management"][1:3] == ("10.20.5.128", 27) and rows["management"][5] == 30


def test_nacl_passes_sample_and_extra_packets():
    for packets in ("network/packets_sample.jsonl", "network/packets_extra.jsonl"):
        out = subprocess.run([sys.executable, "tools/nacl_sim.py", "network/nacl.json", packets, "--check"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
        assert "WRONG" not in out, out


def test_nacl_deny_rule_comes_first():
    rules = json.load(open(os.path.join(ROOT, "network", "nacl.json")))
    first = min(rules["inbound"], key=lambda r: r["rule"])
    assert first["cidr"] == "198.51.100.0/24" and first["action"] == "deny"
