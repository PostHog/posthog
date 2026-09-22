"""Publish an exported checkpoint that sits on a remote box, without giving the box any AWS credential.

    uv run python bin/upload_via_box.py --host ubuntu@<ip> --key ~/.ssh/<key> --remote-src ~/kev-vllm/build/kev-4b

This machine holds the credentials: it creates the multipart upload, presigns one URL per part and one per small file,
and completes the upload. The box receives the URLs over ssh, PUTs the bytes in parallel with the standard library, and
returns the ETags. Same destination layout and provenance file as kev-vllm-upload; same refusal of a non-empty prefix.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys

import boto3
from botocore.config import Config

# The ML training account's base-models bucket; named by the operator, not the public repo.
BUCKET = os.environ.get("KEV_VLLM_BASE_MODELS_BUCKET", "")
PROVENANCE_PREFIX = "_provenance"
PART_SIZE = 256 * 1024**2
SINGLE_PUT_LIMIT = 4 * 1024**3

WORKER = r"""
import json, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
job = json.load(sys.stdin)
root = job["root"]

def put(url, data, create_once=False):
    headers = {"Content-Type": "application/octet-stream"}
    if create_once:
        headers["If-None-Match"] = "*"
    req = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.headers["ETag"]

def put_file(item):
    with open(f"{root}/{item['name']}", "rb") as f:
        return item["name"], put(item["url"], f.read(), create_once=True)

def put_part(item):
    with open(f"{root}/{job['multipart']['name']}", "rb") as f:
        f.seek((item["n"] - 1) * job["multipart"]["part_size"])
        data = f.read(job["multipart"]["part_size"])
    etag = put(item["url"], data)
    print(f"part {item['n']} done", file=sys.stderr, flush=True)
    return item["n"], etag

with ThreadPoolExecutor(max_workers=8) as pool:
    files = dict(pool.map(put_file, job["files"]))
    parts = dict(pool.map(put_part, job["multipart"]["parts"])) if job.get("multipart") else {}
print(json.dumps({"files": files, "parts": parts}))
"""


def ssh(host: str, key: str, command: str, stdin: str | None = None) -> str:
    result = subprocess.run(["ssh", "-i", key, "-o", "ConnectTimeout=20", host, command], input=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ssh failed: {result.stderr.strip()}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--remote-src", required=True, help="exported checkpoint directory on the box")
    parser.add_argument("--model", default="kev-4b")
    parser.add_argument("--version", default=None)
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--profile", default="ml-prod-us-write")
    parser.add_argument("--expires", type=int, default=3600)
    args = parser.parse_args()
    if not args.bucket:
        parser.error("pass --bucket or set KEV_VLLM_BASE_MODELS_BUCKET")

    manifest = json.loads(ssh(args.host, args.key, f"cat {args.remote_src}/manifest.json"))
    version = args.version or manifest.get("kev_hub_revision")
    if not version:
        raise SystemExit("no --version and the remote manifest has no kev_hub_revision")
    prefix = f"posthog/{args.model}-vllm/{version}/"
    # SigV2 presigned URLs sign the Content-Type header, which the client cannot know; SigV4 signs only the host.
    s3 = boto3.Session(profile_name=args.profile).client("s3", config=Config(signature_version="s3v4"))
    if s3.list_objects_v2(Bucket=args.bucket, Prefix=prefix, MaxKeys=1).get("KeyCount", 0):
        raise SystemExit(f"refusing to write into s3://{args.bucket}/{prefix}: not empty")

    files = dict(manifest["files"])
    files["manifest.json"] = {"size_bytes": int(ssh(args.host, args.key, f"stat -c %s {args.remote_src}/manifest.json"))}
    job: dict = {"root": args.remote_src, "files": [], "multipart": None}
    upload_id, big = None, None
    for name, meta in sorted(files.items()):
        key = prefix + name
        if meta["size_bytes"] < SINGLE_PUT_LIMIT:
            # The signed request carries If-None-Match, so the box's PUT is a create-once write too.
            url = s3.generate_presigned_url(
                "put_object", Params={"Bucket": args.bucket, "Key": key, "IfNoneMatch": "*"}, ExpiresIn=args.expires
            )
            job["files"].append({"name": name, "url": url})
        else:
            if big is not None:
                raise SystemExit("only one file above the single PUT limit is supported")
            big = name
            upload_id = s3.create_multipart_upload(Bucket=args.bucket, Key=key)["UploadId"]
            n_parts = -(-meta["size_bytes"] // PART_SIZE)
            parts = [
                {
                    "n": n,
                    "url": s3.generate_presigned_url(
                        "upload_part",
                        Params={"Bucket": args.bucket, "Key": key, "UploadId": upload_id, "PartNumber": n},
                        ExpiresIn=args.expires,
                    ),
                }
                for n in range(1, n_parts + 1)
            ]
            job["multipart"] = {"name": name, "part_size": PART_SIZE, "parts": parts}
            print(f"{name}: {n_parts} parts of {PART_SIZE >> 20} MB", file=sys.stderr)

    try:
        result = run_worker(args, job)
        if big is not None:
            etags = [{"PartNumber": int(n), "ETag": etag} for n, etag in sorted(result["parts"].items(), key=lambda kv: int(kv[0]))]
            s3.complete_multipart_upload(
                Bucket=args.bucket, Key=prefix + big, UploadId=upload_id, MultipartUpload={"Parts": etags}, IfNoneMatch="*"
            )
    except BaseException:
        if upload_id is not None:
            s3.abort_multipart_upload(Bucket=args.bucket, Key=prefix + big, UploadId=upload_id)
        raise

    rows = []
    for name, meta in sorted(files.items()):
        size = s3.head_object(Bucket=args.bucket, Key=prefix + name)["ContentLength"]
        if size != meta["size_bytes"]:
            raise SystemExit(f"size mismatch after upload for {name}: {size} != {meta['size_bytes']}")
        if "sha256" in meta:
            rows.append(f"{name}\tsha256\t{meta['sha256']}\t{size}")
    header = (
        f"# derived: {manifest.get('kev_run')} at Hub revision {manifest.get('kev_hub_revision')}, "
        f"exported {manifest.get('exported_at')}, uploaded from a remote box via presigned URLs\n"
        "# columns: path<TAB>algo<TAB>expected_hash<TAB>size_bytes\n"
    )
    s3.put_object(
        Bucket=args.bucket,
        Key=f"{PROVENANCE_PREFIX}/{prefix}checksums.tsv",
        Body=(header + "\n".join(rows) + "\n").encode(),
        IfNoneMatch="*",
    )
    print(f"done: s3://{args.bucket}/{prefix} ({len(files)} files)")


def run_worker(args: argparse.Namespace, job: dict) -> dict:
    """Run the stdlib worker on the box: the script goes on the command line, the presigned URLs on stdin, so nothing lands on its disk."""
    result = subprocess.run(
        ["ssh", "-i", args.key, "-o", "ConnectTimeout=20", args.host, f"python3 -c {shlex.quote(WORKER)}"],
        input=json.dumps(job),
        capture_output=True,
        text=True,
    )
    sys.stderr.write(result.stderr[-3000:])
    if result.returncode != 0:
        raise SystemExit("remote upload failed")
    return json.loads(result.stdout.strip().splitlines()[-1])


if __name__ == "__main__":
    main()
