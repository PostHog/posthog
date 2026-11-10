import os
import sys
import shlex
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest

from parameterized import parameterized


class TestCodexEnvironment(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source_root = Path(__file__).resolve().parents[4]
        shutil.copytree(source_root / ".codex", self.root / ".codex")
        for filename in (
            ".flox/env/manifest.toml",
            ".flox/env/on-activate.sh",
            "bin/dev-sandbox",
            "bin/dev-sandbox.sb",
            "pnpm-lock.yaml",
            "uv.lock",
        ):
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (self.root / "tools/phrocs").mkdir(parents=True)
        venv_bin = self.root / ".flox/cache/venv/bin"
        venv_bin.mkdir(parents=True)
        python = venv_bin / "python"
        python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
        python.chmod(0o755)
        flox = self.root / "bin/flox"
        flox.write_text(
            "#!/bin/bash\nset -eu\n"
            'test -z "${SSH_AUTH_SOCK+x}"\n'
            'export FLOX_ENV_CACHE="$3/.flox/cache"\n'
            'export DOTENV_FILE="$3/.env"\n'
            'shift 4\nexec "$@"\n'
        )
        flox.chmod(0o755)
        self.environment = {"HOME": str(self.root), "PATH": f"{self.root / 'bin'}:{os.defpath}"}
        self.launcher = str(self.root / ".codex/with-flox")
        subprocess.run(
            [self.launcher, "--prepare", "true"],
            cwd=self.root,
            env={**self.environment, "SSH_AUTH_SOCK": "/tmp/preparation-agent"},
            check=True,
            capture_output=True,
            text=True,
        )

    @parameterized.expand(
        [
            ("absent", None, None, False),
            ("inherited", "/tmp/runtime-agent", None, False),
            ("dotenv", "/tmp/runtime-agent", "EXAMPLE_VALUE=example\n", False),
            ("dotenv_override", "/tmp/runtime-agent", "SSH_AUTH_SOCK=/tmp/dotenv-agent\n", True),
            ("dotenv_injection", None, "SSH_AUTH_SOCK=/tmp/dotenv-agent\n", True),
        ]
    )
    def test_runtime_signing_socket(self, _name: str, socket: str | None, dotenv: str | None, rejected: bool) -> None:
        if dotenv is not None:
            (self.root / ".env").write_text(dotenv)
        environment = self.environment.copy()
        if socket is not None:
            environment["SSH_AUTH_SOCK"] = socket
        result = subprocess.run(
            [self.launcher, "/bin/sh", "-c", 'printf "%s" "${SSH_AUTH_SOCK-unset}"'],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
        )
        if rejected:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(".env cannot override protected variables: SSH_AUTH_SOCK", result.stderr)
        else:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, socket if socket is not None else "unset")
        self.assertNotIn(b"SSH_AUTH_SOCK=", (self.root / ".flox/cache/codex-env").read_bytes())
