"""Small S3 helper for SeaweedFS (run on the laptop; credentials from .secrets/s3.env or the environment).

  python scripts/s3_tool.py mb BUCKET [BUCKET ...]          create buckets (idempotent)
  python scripts/s3_tool.py put LOCAL_FILE s3://BUCKET/KEY
  python scripts/s3_tool.py get s3://BUCKET/KEY LOCAL_FILE
  python scripts/s3_tool.py put-dir LOCAL_DIR s3://BUCKET/PREFIX
  python scripts/s3_tool.py get-dir s3://BUCKET/PREFIX LOCAL_DIR
  python scripts/s3_tool.py ls [s3://BUCKET[/PREFIX]]
"""
import os
import sys


def load_env():
    if os.path.exists(".secrets/s3.env"):
        for line in open(".secrets/s3.env"):
            k, _, v = line.strip().partition("=")
            if k:
                os.environ.setdefault(k, v)
    os.environ.setdefault("S3_ENDPOINT", "http://localhost:8333")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


def split(uri):
    assert uri.startswith("s3://"), uri
    bucket, _, key = uri[5:].partition("/")
    return bucket, key


def main():
    load_env()
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"])
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "mb":
        have = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
        for b in args:
            if b not in have:
                s3.create_bucket(Bucket=b)
            print("bucket", b, "ok")
    elif cmd == "put":
        b, k = split(args[1])
        s3.upload_file(args[0], b, k)
        print("uploaded", args[0], "->", args[1])
    elif cmd == "get":
        b, k = split(args[0])
        os.makedirs(os.path.dirname(args[1]) or ".", exist_ok=True)
        s3.download_file(b, k, args[1])
        print("downloaded", args[0], "->", args[1])
    elif cmd == "put-dir":
        b, prefix = split(args[1])
        for root, _, files in os.walk(args[0]):
            for f in sorted(files):
                p = os.path.join(root, f)
                k = prefix.rstrip("/") + "/" + os.path.relpath(p, args[0]).replace(os.sep, "/")
                s3.upload_file(p, b, k)
                print("uploaded", p, "->", f"s3://{b}/{k}")
    elif cmd == "get-dir":
        b, prefix = split(args[0])
        for o in s3.list_objects_v2(Bucket=b, Prefix=prefix.rstrip("/") + "/").get("Contents", []):
            dest = os.path.join(args[1], o["Key"][len(prefix.rstrip("/")) + 1:])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            s3.download_file(b, o["Key"], dest)
            print("downloaded", f"s3://{b}/{o['Key']}")
    elif cmd == "ls":
        if not args:
            for bk in s3.list_buckets().get("Buckets", []):
                print(bk["Name"])
        else:
            b, prefix = split(args[0])
            for o in s3.list_objects_v2(Bucket=b, Prefix=prefix).get("Contents", []):
                print(f"{o['Size']:>12}  s3://{b}/{o['Key']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
