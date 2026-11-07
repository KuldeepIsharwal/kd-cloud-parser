"""Service tests with a fake model (no weights, no object storage needed)."""
import importlib
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "service"))
sys.path.insert(0, os.path.join(ROOT, "training"))

GOOD = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'


def make_client(monkeypatch, fault="0", output=GOOD, ready=True):
    monkeypatch.setenv("SKIP_MODEL_LOAD", "1")
    monkeypatch.setenv("FAULT_INJECT", fault)
    monkeypatch.setenv("MODEL_VERSION", "v9")
    monkeypatch.setenv("POD_NAME", "parser-test-pod")
    monkeypatch.setenv("SCHEMA_PATH", os.path.join(ROOT, "data", "schema.json"))
    import app as app_module
    app_module = importlib.reload(app_module)
    app_module.state["ready"] = ready
    monkeypatch.setattr(app_module, "generate", lambda text: output)
    return TestClient(app_module.app)


def test_parse_ok_and_headers(monkeypatch):
    c = make_client(monkeypatch)
    r = c.post("/parse", json={"text": "what is the weather in london"})
    assert r.status_code == 200
    assert r.json() == json.loads(GOOD)
    assert r.headers["X-Model-Version"] == "v9"
    assert r.headers["X-Served-By"] == "parser-test-pod"


def test_fault_inject_returns_500(monkeypatch):
    c = make_client(monkeypatch, fault="1")
    r = c.post("/parse", json={"text": "anything"})
    assert r.status_code == 500
    assert r.json() == {"error": "invalid_model_output"}


@pytest.mark.parametrize("bad", ['{"intent": "weather_query"}', '{"intent": "x", "date": null, "time": null, "place": null}',
                                 '{"intent": "alarm_set", "date": 5, "time": null, "place": null}', '{"intent": "alarm_s'])
def test_invalid_outputs_never_200(monkeypatch, bad):
    c = make_client(monkeypatch, output=bad)
    r = c.post("/parse", json={"text": "x"})
    assert r.status_code == 500 and r.json() == {"error": "invalid_model_output"}


def test_health_and_readiness(monkeypatch):
    c = make_client(monkeypatch, ready=False)
    assert c.get("/healthz").status_code == 200
    assert c.get("/readyz").status_code == 503
    import app as app_module
    app_module.state["ready"] = True
    assert c.get("/readyz").status_code == 200


def test_common_cut_output_and_validity():
    from common import cut_output, is_valid
    assert cut_output(" " + GOOD + "\nCommand: next") == GOOD
    intents = set(json.load(open(os.path.join(ROOT, "data", "schema.json")))["intents"])
    assert is_valid(GOOD, intents)
    assert not is_valid("not json", intents)
