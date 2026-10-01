from __future__ import annotations

import os
import sys
import hashlib
import argparse
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

from products.posthog_ai.eval_harness.environment.storage import (
    file_sha256,
    require_private_path,
    validate_sha256,
    workspace_lock,
)

MAX_TRANSFER_BYTES = 2 * 1024**3


class EnvironmentTransfer:
    def __init__(self, workspace: Path, *, sha256: str, size: int) -> None:
        self.sha256 = validate_sha256(sha256)
        if not 0 < size <= MAX_TRANSFER_BYTES:
            raise ValueError("The bundle must be nonempty and at most 2 GiB")
        self.size = size
        self.workspace = require_private_path(workspace)
        self.path = self.workspace / f"upload-{self.sha256}.tar.gz"

    def check(self) -> bool:
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ValueError("The uploaded bundle must be a private regular file")
        if not self.path.exists():
            return False
        if self.path.stat().st_size != self.size or file_sha256(self.path) != self.sha256:
            raise ValueError("The cached upload is corrupt; remove that archive before retrying")
        self.path.chmod(0o600)
        return True

    def receive(self, source: BinaryIO) -> Path:
        with workspace_lock(self.workspace):
            self.check()
            with tempfile.TemporaryDirectory(prefix=".upload-", dir=self.workspace) as temporary:
                partial = Path(temporary) / "bundle.tar.gz"
                descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                digest = hashlib.sha256()
                transferred = 0
                with os.fdopen(descriptor, "wb") as output:
                    while block := source.read(min(1024 * 1024, self.size - transferred + 1)):
                        transferred += len(block)
                        if transferred > self.size:
                            raise ValueError("The upload exceeds its declared size")
                        digest.update(block)
                        output.write(block)
                    if transferred != self.size:
                        raise ValueError("The bundle upload was interrupted; rerun the command to retry")
                    if digest.hexdigest() != self.sha256:
                        raise ValueError("The uploaded bundle does not match its SHA-256; no data was imported")
                    output.flush()
                    os.fsync(output.fileno())
                if not self.check():
                    os.link(partial, self.path)
        return self.path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Receive a private evaluation bundle over SSH")
    parser.add_argument("command", choices=("check", "receive"))
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        transfer = EnvironmentTransfer(args.state_dir, sha256=args.sha256, size=args.size)
        if args.command == "check":
            return 0 if transfer.check() else 3
        transfer.receive(sys.stdin.buffer)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Environment transfer failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
