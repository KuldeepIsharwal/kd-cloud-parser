import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "worker"))

from clean import clean, serialise  # noqa: E402
from worker import build_prompt, shard_lines  # noqa: E402


def rec(i, text, raw):
    return {"id": f"C{i:04d}", "text": text, "teacher_raw": raw}


def good(intent="weather_query", date=None, time=None, place=None):
    return json.dumps({"intent": intent, "date": date, "time": time, "place": place})


def test_sharding_covers_every_line_exactly_once():
    lines = [f"l{i}" for i in range(3000)]
    shards = [shard_lines(lines, i, 4) for i in range(4)]
    flat = [x for s in shards for x in s]
    assert sorted(flat) == sorted(lines)
    assert len(flat) == len(set(flat))
    assert shards[1][:2] == ["l1", "l5"]


def test_prompt_contains_command():
    assert build_prompt("A\nCommand: {command}\n", "wake me up") == "A\nCommand: wake me up\n"


def test_clean_rejection_reasons_and_counts():
    rows = [
        rec(1, "what is the weather in london", good(place="london")),
        rec(2, "what is the weather in paris", "```json\n{}\n```"),                       # (a)
        rec(3, "what is the weather in rome", '{"intent": "weather_query"}'),            # (b)
        rec(4, "play music", good(intent="play_music")),                                 # (c)
        rec(5, "weather in oslo", good(place="bergen")),                                 # (d) invented
        rec(6, "What is the weather in  London", good(place="london")),                  # (e) duplicate of 1
        rec(7, "set an alarm for seven am", good("alarm_set", time="seven am")),
    ]
    kept, counts = clean(rows)
    assert counts == {"input": 7, "not_json": 1, "bad_keys": 1, "bad_intent": 1,
                      "bad_slot": 1, "duplicate": 1, "kept": 2}
    assert [k["id"] for k in kept] == ["C0001", "C0007"]
    assert json.loads(kept[1]["target"])["time"] == "seven am"


def test_clean_keeps_smallest_id_and_sorts():
    rows = [rec(9, "wake me at six", good("alarm_set", time="six")),
            rec(3, "wake me at six", good("alarm_set", time="six")),
            rec(5, "weather today", good(date="today"))]
    kept, counts = clean(rows)
    assert [k["id"] for k in kept] == ["C0003", "C0005"]
    assert counts["duplicate"] == 1


def test_clean_is_deterministic():
    rows = [rec(i, f"weather in city{i}", good(place=f"city{i}")) for i in range(20)]
    a = serialise(clean(rows)[0])
    b = serialise(clean(list(reversed(rows)))[0])
    assert a == b
