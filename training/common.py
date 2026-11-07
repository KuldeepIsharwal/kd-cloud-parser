"""Prompt format and decoding shared by training, offline evaluation and the service."""
import json

KEYS = ("intent", "date", "time", "place")
INTENTS = ("alarm_set", "alarm_query", "calendar_set", "calendar_query",
           "calendar_remove", "weather_query", "datetime_query", "recommendation_events")
INTENT_PREFIX = ' {"intent": "'


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


def greedy_generate(model, tok, command, max_new_tokens):
    """Plain greedy decoding (used for the 'unconstrained' comparison)."""
    import torch
    enc = tok(prompt_for(command), return_tensors="pt")
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                             pad_token_id=tok.eos_token_id, eos_token_id=tok.eos_token_id)
    return cut_output(tok.decode(out[0, enc["input_ids"].shape[1]:], skip_special_tokens=True))


def constrained_generate(model, tok, command, max_new_tokens, intents=INTENTS):
    """Schema-constrained decoding.

    1. Force the start of the object: ' {"intent": "'.
    2. Choose the intent among the allowed values only, by the model's own log-likelihood
       of '<intent>"' after that prefix (one batched forward pass over the 8 candidates).
    3. Append ', "date":' and let the model generate the slots greedily, cut at the first newline.
    The model still decides everything; it just cannot name an intent outside the schema.
    """
    import torch
    prefix = prompt_for(command) + INTENT_PREFIX
    # Tokenise each full candidate jointly (as in training) and score the tokens after the
    # longest prefix that all candidates share, so BPE merges at the boundary do not matter.
    seqs = [tok(prefix + i + '",')["input_ids"] for i in intents]
    shared = 0
    while all(len(s) > shared for s in seqs) and len({s[shared] for s in seqs}) == 1:
        shared += 1
    width = max(len(s) for s in seqs)
    ids = torch.full((len(seqs), width), tok.eos_token_id)
    att = torch.zeros((len(seqs), width), dtype=torch.long)
    for r, s in enumerate(seqs):
        ids[r, :len(s)] = torch.tensor(s)
        att[r, :len(s)] = 1
    with torch.no_grad():
        logp = torch.log_softmax(model(input_ids=ids, attention_mask=att).logits, dim=-1)
    scores = [sum(logp[r, j - 1, s[j]].item() for j in range(shared, len(s))) for r, s in enumerate(seqs)]
    intent = intents[max(range(len(intents)), key=lambda i: scores[i])]

    head = '{"intent": "' + intent + '", "date":'
    enc = tok(prompt_for(command) + " " + head, return_tensors="pt")
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                             pad_token_id=tok.eos_token_id, eos_token_id=tok.eos_token_id)
    tail = tok.decode(out[0, enc["input_ids"].shape[1]:], skip_special_tokens=True)
    return cut_output(head + tail)
