#!/usr/bin/env bash
# Task 2 step 6: score the untrained base model and the students on validation.jsonl,
# with schema-constrained decoding (what the service does) and plain greedy decoding.
# The teacher is scored separately by eval/predict_teacher.py (needs Ollama).
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
R=results
run() {  # name model decoding
  python eval/predict_student.py "$2" data/validation.jsonl "$R/${1}_validation_predictions.jsonl" --decoding "$3"
  python tools/score.py "$R/${1}_validation_predictions.jsonl" data/validation.jsonl --out "$R/${1}_validation.json" \
    | tee "$R/${1}_validation_score.txt"
}
run untrained            EleutherAI/pythia-70m constrained
run untrained_greedy     EleutherAI/pythia-70m greedy
run student_v1           build/models/v1       constrained
run student_v1_greedy    build/models/v1       greedy
run student_v2           build/models/v2       constrained
run student_v2_greedy    build/models/v2       greedy
