import os
import json
import shutil
import tempfile
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from products.skills.backend.marketplace import git_smart_http as git
from products.skills.backend.marketplace.packaging import (
    SkillExport,
    SkillFileExport,
    build_marketplace_tree,
    compute_plugin_version,
)

# End-to-end proof that the synthesized repo is clonable by a real git client (and therefore
# by Claude Code's `/plugin marketplace add`). DB-free; skipped where the git binary is absent.

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


def _marketplace_tree(epoch: int) -> dict[str, str]:
    skill = SkillExport(
        name="make-fractals",
        description="Render fractal images. Use when asked to visualize fractals.",
        body="# make-fractals\n\nDo the thing.\n",
        version=2,
        allowed_tools=["Bash", "Write"],
        files=[SkillFileExport(path="scripts/mandelbrot.py", content="print('hi')\n", content_type="text/x-python")],
    )
    return build_marketplace_tree(
        plugin_name="posthog-skill-store",
        plugin_description="Team skills",
        plugin_version=compute_plugin_version(epoch),
        owner_name="PostHog",
        marketplace_name="posthog-skill-store-marketplace",
        skills=[skill],
    )


class _GitServer:
    def __init__(self):
        self._epoch = 1700000000

        def repo():
            return git.synthesize_repo(_marketplace_tree(self._epoch), author="PostHog", message="marketplace")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.split("?")[0].endswith("/info/refs"):
                    body = git.build_info_refs(repo().head_sha)
                    self._send(git.INFO_REFS_CONTENT_TYPE, body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path.endswith("/git-upload-pack"):
                    length = int(self.headers.get("Content-Length", 0))
                    body = git.build_upload_pack(self.rfile.read(length), repo())
                    self._send(git.UPLOAD_PACK_CONTENT_TYPE, body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def _send(self, content_type: str, body: bytes):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/marketplace.git"

    def set_epoch(self, epoch: int):
        self._epoch = epoch

    def stop(self):
        self._server.shutdown()


def _clone(url: str, dest: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "clone", "--quiet", *extra, url, dest],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _plugin_version(checkout: str) -> str:
    with open(os.path.join(checkout, ".claude-plugin", "marketplace.json")) as handle:
        return json.load(handle)["plugins"][0]["version"]


@pytest.fixture
def git_server():
    server = _GitServer()
    try:
        yield server
    finally:
        server.stop()


def test_full_clone_yields_spec_marketplace_tree(git_server):
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, "checkout")
        result = _clone(git_server.url, dest)
        assert result.returncode == 0, result.stderr

        skill_md = os.path.join(dest, "plugins", "posthog-skill-store", "skills", "make-fractals", "SKILL.md")
        script = os.path.join(
            dest, "plugins", "posthog-skill-store", "skills", "make-fractals", "scripts", "mandelbrot.py"
        )
        assert os.path.exists(skill_md)
        assert os.path.exists(script)
        assert "allowed-tools: Bash Write" in open(skill_md).read()

        fsck = subprocess.run(["git", "-C", dest, "fsck", "--full"], capture_output=True, text=True)
        assert fsck.returncode == 0, fsck.stderr


def test_shallow_clone_succeeds(git_server):
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, "checkout")
        result = _clone(git_server.url, dest, "--depth", "1")
        assert result.returncode == 0, result.stderr


def test_content_change_bumps_plugin_version(git_server):
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "first")
        assert _clone(git_server.url, first).returncode == 0
        before = _plugin_version(first)

        git_server.set_epoch(1700009999)
        second = os.path.join(tmp, "second")
        assert _clone(git_server.url, second).returncode == 0
        after = _plugin_version(second)

    assert before != after
    assert after > before
