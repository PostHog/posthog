from __future__ import annotations

import io
import sys
import hashlib
import tempfile
import subprocess
from pathlib import Path

from unittest import TestCase

from parameterized import parameterized

from products.posthog_ai.eval_harness.environment.storage import workspace_lock
from products.posthog_ai.eval_harness.environment.transfer import EnvironmentTransfer, main


class TestEnvironmentTransfer(TestCase):
    def test_stdin_transfer_is_private_verified_and_reusable(self) -> None:
        content = b"invented archive content"
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "private state ; $example"
            arguments = ["--sha256", digest, "--size", str(len(content)), "--state-dir", str(workspace)]
            self.assertEqual(main(["check", *arguments]), 3)
            result = subprocess.run(
                [sys.executable, "-m", "products.posthog_ai.eval_harness.environment.transfer", "receive", *arguments],
                input=content,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(main(["check", *arguments]), 0)
            transfer = EnvironmentTransfer(workspace, sha256=digest, size=len(content))
            uploaded = transfer.path
            self.assertEqual(uploaded.read_bytes(), content)
            self.assertEqual(uploaded.stat().st_mode & 0o777, 0o600)
            self.assertEqual(workspace.stat().st_mode & 0o777, 0o700)
            modification = uploaded.stat().st_mtime_ns
            self.assertEqual(transfer.receive(io.BytesIO(content)), uploaded)
            self.assertEqual(uploaded.stat().st_mtime_ns, modification)
            self.assertEqual({item.name for item in workspace.iterdir()}, {uploaded.name, ".lock"})

    @parameterized.expand(["short", "long", "wrong_digest", "read_error"])
    def test_failed_transfer_cleans_partial_file_and_allows_retry(self, failure: str) -> None:
        content = b"invented archive content"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "state"
            transfer = EnvironmentTransfer(workspace, sha256=hashlib.sha256(content).hexdigest(), size=len(content))

            class InterruptedStream(io.BytesIO):
                def read(self, size: int | None = -1) -> bytes:
                    if self.tell():
                        raise OSError("Connection lost")
                    return super().read(1)

            streams = {
                "short": io.BytesIO(content[:-1]),
                "long": io.BytesIO(content + b"extra"),
                "wrong_digest": io.BytesIO(b"X" * len(content)),
                "read_error": InterruptedStream(content),
            }
            with self.assertRaises((OSError, ValueError)):
                transfer.receive(streams[failure])
            self.assertFalse(transfer.check())
            self.assertEqual([item.name for item in workspace.iterdir()], [".lock"])
            self.assertEqual(transfer.receive(io.BytesIO(content)).read_bytes(), content)

    @parameterized.expand(["symlink", "directory", "corrupt"])
    def test_cached_upload_is_never_silently_replaced(self, failure: str) -> None:
        content = b"invented archive content"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            transfer = EnvironmentTransfer(workspace, sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            original = workspace / "original"
            original.write_bytes(b"do not change")
            if failure == "symlink":
                transfer.path.symlink_to(original)
            elif failure == "directory":
                transfer.path.mkdir()
            else:
                transfer.path.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                transfer.check()
            with self.assertRaises(ValueError):
                transfer.receive(io.BytesIO(content))
            self.assertEqual(original.read_bytes(), b"do not change")
            if failure == "corrupt":
                self.assertEqual(transfer.path.read_bytes(), b"corrupt")

    def test_active_preparation_blocks_upload_into_same_state(self) -> None:
        content = b"invented archive content"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            transfer = EnvironmentTransfer(workspace, sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            with workspace_lock(workspace), self.assertRaisesRegex(ValueError, "Another fixture preparation"):
                transfer.receive(io.BytesIO(content))
            self.assertFalse(transfer.path.exists())

    @parameterized.expand([("bad_digest", "../outside", 1), ("empty", "0" * 64, 0), ("oversized", "0" * 64, 2**31 + 1)])
    def test_invalid_transfer_metadata_does_not_create_state(self, _: str, digest: str, size: int) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "state"
            with self.assertRaises(ValueError):
                EnvironmentTransfer(workspace, sha256=digest, size=size)
            self.assertFalse(workspace.exists())
