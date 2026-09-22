"""Upload an exported checkpoint directory to the ML training account's base-models bucket.

    kev-vllm-upload --src build/kev-4b --version <kev hub revision> --profile ml-prod-us-write

Objects land under `posthog/<model>-vllm/<version>/`, one prefix per export, never overwritten: the upload refuses a
prefix that already holds anything, and every write carries If-None-Match so S3 itself refuses to replace an object
(412) whatever the client does. Subdirectories go along, which is how the `parity/` fixture travels with the weights
it was measured against. A `checksums.tsv` in the bucket's `_provenance/` layout records every file's sha256 and size,
so a consumer can verify what it fetched.
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from kev_vllm.checkpoint import sha256_of

# The ML training account's base-models bucket; named by the operator, not the public repo.
BUCKET = os.environ.get("KEV_VLLM_BASE_MODELS_BUCKET", "")
PROVENANCE_PREFIX = "_provenance"


PART_SIZE = 256 * 1024**2
SINGLE_PUT_LIMIT = 4 * 1024**3


def put_create_once(s3, bucket: str, key: str, body, digest: str) -> None:
    s3.put_object(Bucket=bucket, Key=key, Body=body, IfNoneMatch="*", ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode())


def multipart_create_once(s3, bucket: str, key: str, path: Path) -> None:
    """The high-level uploader cannot send If-None-Match, so the multipart dance is written out; only the completing
    call carries the header, which is the one the bucket policy checks."""
    upload_id = s3.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
    try:
        parts = []
        with path.open("rb") as f:
            for number in range(1, 10_001):
                chunk = f.read(PART_SIZE)
                if not chunk:
                    break
                etag = s3.upload_part(Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=number, Body=chunk)["ETag"]
                parts.append({"PartNumber": number, "ETag": etag})
        s3.complete_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}, IfNoneMatch="*")
    except BaseException:
        s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        raise


def prefix_is_empty(s3, bucket: str, prefix: str) -> bool:
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    return response.get("KeyCount", 0) == 0


def upload(src: Path, bucket: str, prefix: str, profile: str | None) -> None:
    session = boto3.Session(profile_name=profile)
    s3 = session.client("s3")
    if not prefix_is_empty(s3, bucket, prefix):
        raise SystemExit(f"refusing to write into s3://{bucket}/{prefix}: the prefix is not empty, pick a new version")
    manifest = json.loads((src / "manifest.json").read_text())
    files = sorted(p for p in src.rglob("*") if p.is_file() and not p.name.startswith("."))
    rows = []
    for path in files:
        relative = path.relative_to(src).as_posix()
        digest = sha256_of(path)
        recorded = manifest.get("files", {}).get(relative, {}).get("sha256")
        if recorded and recorded != digest:
            raise SystemExit(f"{relative} does not match manifest.json ({digest} != {recorded}); re-export")
        key = f"{prefix}{relative}"
        size = path.stat().st_size
        print(f"put s3://{bucket}/{key} ({size / 1e9:.2f} GB)", file=sys.stderr)
        try:
            if size < SINGLE_PUT_LIMIT:
                with path.open("rb") as body:
                    put_create_once(s3, bucket, key, body, digest)
            else:
                # Above the single PUT limit the whole-file sha256 is only recorded in checksums.tsv.
                multipart_create_once(s3, bucket, key, path)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "PreconditionFailed":
                raise SystemExit(f"s3://{bucket}/{key} already exists; a published version is never replaced") from error
            raise
        head = s3.head_object(Bucket=bucket, Key=key)
        if head["ContentLength"] != size:
            raise SystemExit(f"size mismatch after upload for {key}")
        rows.append(f"{relative}\tsha256\t{digest}\t{size}")
    header = (
        f"# derived: {manifest.get('kev_run')} at Hub revision {manifest.get('kev_hub_revision')}, "
        f"exported {manifest.get('exported_at')}\n"
        "# columns: path<TAB>algo<TAB>expected_hash<TAB>size_bytes\n"
    )
    s3.put_object(
        Bucket=bucket, Key=f"{PROVENANCE_PREFIX}/{prefix}checksums.tsv", Body=(header + "\n".join(rows) + "\n").encode(), IfNoneMatch="*"
    )
    print(f"done: s3://{bucket}/{prefix}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, required=True, help="directory written by kev-vllm-export")
    parser.add_argument("--model", default="kev-4b")
    parser.add_argument("--version", help="defaults to the Kev Hub revision in manifest.json")
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--profile", help="an AWS profile with write access; omitted, boto3 uses the ambient credentials")
    args = parser.parse_args()
    if not args.bucket:
        parser.error("pass --bucket or set KEV_VLLM_BASE_MODELS_BUCKET")
    manifest = json.loads((args.src / "manifest.json").read_text())
    version = args.version or manifest.get("kev_hub_revision")
    if not version:
        raise SystemExit("no --version and manifest.json has no kev_hub_revision (local run); pass --version")
    upload(args.src, args.bucket, f"posthog/{args.model}-vllm/{version}/", args.profile)


if __name__ == "__main__":
    main()
