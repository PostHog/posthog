import hashlib
import json
from pathlib import Path

import pytest

from kev_vllm.checkpoint import verify


def write_checkpoint(tmp_path: Path, tamper: str | None = None) -> Path:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"weights")
    manifest = {"kev_run": "run", "files": {"model.safetensors": {"sha256": hashlib.sha256(b"weights").hexdigest()}}}
    if tamper == "no_files_table":
        del manifest["files"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if tamper == "bytes":
        weights.write_bytes(b"weight5")
    if tamper == "missing":
        weights.unlink()
    return tmp_path


def test_verify_accepts_a_checkpoint_that_matches_its_manifest(tmp_path: Path) -> None:
    assert verify(write_checkpoint(tmp_path))["kev_run"] == "run"


@pytest.mark.parametrize("tamper", ["bytes", "missing"])
def test_verify_rejects_a_checkpoint_that_drifted_from_its_manifest(tmp_path: Path, tamper: str) -> None:
    with pytest.raises(ValueError, match=r"model\.safetensors"):
        verify(write_checkpoint(tmp_path, tamper))


def test_verify_rejects_a_manifest_without_a_files_table(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no files table"):
        verify(write_checkpoint(tmp_path, "no_files_table"))


def test_verify_rejects_a_directory_without_a_manifest(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify(tmp_path)
