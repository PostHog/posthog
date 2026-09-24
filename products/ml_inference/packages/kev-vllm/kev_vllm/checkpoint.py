"""Verify an exported checkpoint directory against the hashes in its manifest.json.

    kev-vllm-checkpoint verify /models/kev-4b

Exit status 0 when every file the manifest lists is present with the recorded sha256, 1 otherwise.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, TypedDict


class ManifestFile(TypedDict):
    sha256: str
    size_bytes: int


class Manifest(TypedDict, total=False):
    """What kev-vllm-export and jevk5-vllm-export write; `files` is the part verification needs, the rest is provenance."""

    kev_run: str
    kev_hub_revision: str
    source_repo: str
    source_revision: str
    files: dict[str, ManifestFile]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(checkpoint_dir: Path) -> Manifest:
    manifest_path = checkpoint_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{checkpoint_dir} has no manifest.json; it is not an exported checkpoint")
    manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise ValueError(f"{manifest_path} has no files table; it is not a manifest kev-vllm-export wrote")
    return manifest


def verify(checkpoint_dir: Path) -> Manifest:
    manifest = read_manifest(checkpoint_dir)
    problems = []
    for name, meta in manifest["files"].items():
        path = checkpoint_dir / name
        if not path.is_file():
            problems.append(f"{name}: missing")
        elif sha256_of(path) != meta["sha256"]:
            problems.append(f"{name}: sha256 mismatch")
    if problems:
        raise ValueError("checkpoint does not match its manifest: " + ", ".join(problems))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("checkpoint_dir", type=Path)
    args = parser.parse_args()
    try:
        manifest = verify(args.checkpoint_dir)
    except (FileNotFoundError, ValueError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
    source = manifest.get("kev_run") or manifest.get("source_repo")
    revision = manifest.get("kev_hub_revision") or manifest.get("source_revision")
    print(f"checkpoint ok: {source} @ {revision}, {len(manifest['files'])} files")


if __name__ == "__main__":
    main()
