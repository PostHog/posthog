import hashlib
import json

import pytest

from kev_vllm.checkpoint import verify


def write_checkpoint(tmp_path, tamper: str | None = None):
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"weights")
    manifest = {"kev_run": "run", "files": {"model.safetensors": {"sha256": hashlib.sha256(b"weights").hexdigest()}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    if tamper == "bytes":
        weights.write_bytes(b"weight5")
    if tamper == "missing":
        weights.unlink()
    return tmp_path


def test_verify_accepts_a_checkpoint_that_matches_its_manifest(tmp_path):
    assert verify(write_checkpoint(tmp_path))["kev_run"] == "run"


@pytest.mark.parametrize("tamper", ["bytes", "missing"])
def test_verify_rejects_a_checkpoint_that_drifted_from_its_manifest(tmp_path, tamper):
    with pytest.raises(ValueError, match=r"model\.safetensors"):
        verify(write_checkpoint(tmp_path, tamper))


def test_verify_rejects_a_directory_without_a_manifest(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify(tmp_path)
