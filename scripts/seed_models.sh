#!/usr/bin/env bash
# Download model tarballs from the GitHub Release, verify their SHA-256 against the
# model.sha256 asset, and upload the extracted files to s3://models/models/<version>/.
# Usage: scripts/seed_models.sh RELEASE_URL v1 [v2 ...]
set -euo pipefail
url="$1"; shift
PY=${PY:-.venv/bin/python}
mkdir -p build/release
for v in "$@"; do
  tgz="pythia70m-kd-${v}.tar.gz"
  curl -fsSL -o "build/release/${tgz}" "${url}/${tgz}"
  curl -fsSL -o "build/release/${v}.model.sha256" "${url}/${v}.model.sha256"
  expected=$(head -1 "build/release/${v}.model.sha256" | cut -d' ' -f1)
  actual=$(sha256sum "build/release/${tgz}" | cut -d' ' -f1)
  [ "$expected" = "$actual" ] || { echo "checksum mismatch for ${tgz}"; exit 1; }
  echo "${tgz}: sha256 OK ${actual}"
  rm -rf "build/release/${v}"
  tar -xzf "build/release/${tgz}" -C build/release
  "$PY" scripts/s3_tool.py put-dir "build/release/${v}" "s3://models/models/${v}"
  "$PY" scripts/s3_tool.py put "build/release/${tgz}" "s3://models/models/${v}/${tgz}"
  "$PY" scripts/s3_tool.py put "build/release/${v}.model.sha256" "s3://models/models/${v}/model.sha256"
done
