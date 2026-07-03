"""Builds the deployable tarball of the in-sandbox kernel package.

The `kernel/` package ships into the sandbox as `nb_kernel/`: `ensure_sql_v2_server`
writes the tarball, extracts it, and launches `python -m nb_kernel.server`. The
content hash doubles as the server version — /health reports it, and a mismatch
with the running server triggers a redeploy (the dev loop needs no image rebuild).
"""

import io
import hashlib
import tarfile
from functools import lru_cache
from pathlib import Path

SANDBOX_PACKAGE_NAME = "nb_kernel"

_KERNEL_DIR = Path(__file__).parent / "kernel"


def _kernel_files() -> list[Path]:
    return sorted(_KERNEL_DIR.glob("*.py"))


@lru_cache(maxsize=1)
def kernel_package_bytes_and_hash() -> tuple[bytes, str]:
    """Return (tar.gz bytes, content hash) of the kernel package, deterministically."""
    digest = hashlib.sha256()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in _kernel_files():
            content = path.read_bytes()
            digest.update(path.name.encode())
            digest.update(content)
            info = tarfile.TarInfo(name=f"{SANDBOX_PACKAGE_NAME}/{path.name}")
            info.size = len(content)
            info.mtime = 0  # keep the archive byte-stable for a given content hash
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue(), digest.hexdigest()[:16]


def kernel_package_hash() -> str:
    return kernel_package_bytes_and_hash()[1]
