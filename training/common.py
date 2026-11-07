"""Prompt format and decoding shared by training, offline evaluation and the service."""
import json

KEYS = ("intent", "date", "time", "place")


def prompt_for(command):
    return f"Command: {command}\nJSON:"


def training_text(command, target_json):
    return f"{prompt_for(command)} {target_json}"


def cut_output(text):
    """Keep the generated answer up to the end of the first line (the model is trained to
    emit one JSON object followed by end-of-text, so anything after a newline is not part
    of the answer)."""
    return text.strip().split("\n", 1)[0].strip()


def is_valid(raw, intents):
    """True if raw is a JSON object with exactly the four keys, a known intent and
    string-or-null slots (the same rules as data/schema.json)."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(obj, dict) or set(obj) != set(KEYS):
        return False
    if obj["intent"] not in intents:
        return False
    return all(obj[k] is None or isinstance(obj[k], str) for k in ("date", "time", "place"))
