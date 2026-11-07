#!/usr/bin/env bash
# Generate random S3 credentials once (kept in .secrets/, which is git-ignored) and
# create the Kubernetes Secrets that use them. Nothing secret is stored in the repository.
set -euo pipefail
mkdir -p .secrets
if [ ! -f .secrets/s3.env ]; then
  echo "AWS_ACCESS_KEY_ID=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')" > .secrets/s3.env
  echo "AWS_SECRET_ACCESS_KEY=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> .secrets/s3.env
  chmod 600 .secrets/s3.env
fi
# shellcheck disable=SC1091
source .secrets/s3.env

cat > .secrets/s3.json <<EOF
{"identities": [{"name": "admin",
  "credentials": [{"accessKey": "${AWS_ACCESS_KEY_ID}", "secretKey": "${AWS_SECRET_ACCESS_KEY}"}],
  "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}
EOF

for ns in data pipeline app; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done
kubectl -n data create secret generic seaweedfs-s3-config --from-file=s3.json=.secrets/s3.json \
  --dry-run=client -o yaml | kubectl apply -f -
for ns in pipeline app; do
  kubectl -n "$ns" create secret generic s3-credentials --from-env-file=.secrets/s3.env \
    --dry-run=client -o yaml | kubectl apply -f -
done
