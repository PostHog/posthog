"""Packages the in-sandbox kernel so it can reach the sandbox two ways.

The `kernel/` package runs in the sandbox as `nb_kernel/`. The notebook sandbox
image bakes it under `BAKED_PACKAGE_ROOT` and stamps its content hash into
`BAKED_VERSION_PATH`, so `ensure_sql_v2_server` launches it in place. When that
stamp does not match the hash the backend expects, the same modules go over the
control plane as a tarball instead. That covers a kernel edit no image build has
picked up: every edit in the dev loop, and the window in production between
merging a kernel change and its image reaching the registry.

The content hash doubles as the server version, so /health reports it and a
mismatch triggers a redeploy.

Running this module as a script prints the hash, and `--baked-root` prints the
directory the image bakes into. The image build calls it both ways, so the paths
and the hash have one definition rather than a copy in the Dockerfile that can
drift out of step with this one.
"""

import io
import sys
import hashlib
import tarfile
from functools import lru_cache
from pathlib import Path

SANDBOX_PACKAGE_NAME = "nb_kernel"

# Where Dockerfile.sandbox-notebook bakes the package. The modules land in
# `<root>/nb_kernel/`, mirroring the tarball layout, so one PYTHONPATH and one
# `-m nb_kernel.server` launch serve both roots.
BAKED_PACKAGE_ROOT = "/opt/nb_kernel_pkg"
BAKED_VERSION_PATH = f"{BAKED_PACKAGE_ROOT}/VERSION"

_KERNEL_DIR = Path(__file__).parent / "sandbox" / "kernel"


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


if __name__ == "__main__":
    _answer = BAKED_PACKAGE_ROOT if "--baked-root" in sys.argv[1:] else kernel_package_hash()
    sys.stdout.write(f"{_answer}\n")
