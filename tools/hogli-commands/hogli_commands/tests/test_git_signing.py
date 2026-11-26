from __future__ import annotations

import os
import sys
import base64
import struct
import hashlib
import subprocess
from pathlib import Path
from typing import Any

import pytest
from unittest import mock

import click
from hogli_commands.git_signing import (
    SecureEnclaveSigningSetup,
    add_allowed_signer,
    forwards_agent_to_devboxes,
    pick_new_key,
    public_key_identity,
)


class TestPickNewKey:
    EXISTING = "sk-ecdsa-sha2-nistp256@openssh.com AAAAEXISTING"
    NEW = "sk-ecdsa-sha2-nistp256@openssh.com AAAANEW"

    def test_ignores_secure_enclave_keys_that_existed_before(self) -> None:
        before = {public_key_identity(f"{self.EXISTING} ssh:")}
        after = {self.EXISTING: Path("id_ecdsa_sk_rk"), self.NEW: Path("id_ecdsa_sk_rk_1")}

        assert pick_new_key(before, after) == Path("id_ecdsa_sk_rk_1")

    @pytest.mark.parametrize(
        "after",
        [
            {EXISTING: Path("id_ecdsa_sk_rk")},
            {EXISTING: Path("id_ecdsa_sk_rk"), NEW: Path("a"), f"{NEW}2": Path("b")},
        ],
    )
    def test_refuses_when_the_new_key_is_ambiguous(self, after: dict[str, Path]) -> None:
        with pytest.raises(click.ClickException):
            pick_new_key({self.EXISTING}, after)


class TestAddAllowedSigner:
    KEY = "sk-ecdsa-sha2-nistp256@openssh.com AAAANEW"

    @pytest.mark.parametrize(
        "existing",
        [
            None,
            'dev@example.com namespaces="git" ssh-ed25519 AAAAOLD\n',
            'dev@example.com namespaces="git" ssh-ed25519 AAAAOLD',
        ],
    )
    def test_appends_the_key_once(self, tmp_path: Path, existing: str | None) -> None:
        signers = tmp_path / "allowed_signers"
        if existing is not None:
            signers.write_text(existing)

        assert add_allowed_signer(signers, "dev@example.com", f"{self.KEY} ssh:\n")
        assert not add_allowed_signer(signers, "dev@example.com", f"{self.KEY} ssh:\n")

        lines = signers.read_text().splitlines()
        assert lines[-1] == f'dev@example.com namespaces="git" {self.KEY}'
        assert len(lines) == (1 if existing is None else 2)


class TestGitHubBeforeGitConfig:
    @pytest.mark.parametrize(
        "listed_after_confirm, configured",
        [(True, True), (False, False)],
    )
    def test_git_config_waits_for_the_key_on_github(
        self, monkeypatch: pytest.MonkeyPatch, listed_after_confirm: bool, configured: bool
    ) -> None:
        setup = SecureEnclaveSigningSetup(use_global=True, repos=())
        local_steps = (
            "_check_platform",
            "_confirm",
            "_install_sign_program",
            "_test_sign",
            "_print_manual_github_steps",
            "_update_allowed_signers",
            "_warn_about_overrides",
            "_print_undo_steps",
        )
        for step in local_steps:
            monkeypatch.setattr(setup, step, mock.Mock())
        monkeypatch.setattr("hogli_commands.git_signing.KEY_PATH", mock.Mock(exists=lambda: True))
        monkeypatch.setattr("hogli_commands.git_signing.shutil.which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(setup, "_gh", lambda *args: subprocess.CompletedProcess(args, 0, stdout="dev\n"))
        monkeypatch.setattr(setup, "_add_to_github", lambda: False)
        on_github = iter([False, listed_after_confirm])
        monkeypatch.setattr(setup, "_is_on_github", lambda login: next(on_github))
        answers = iter([True, False])

        def confirm(*args: object, **kwargs: object) -> bool:
            if not next(answers):
                raise click.Abort()
            return True

        monkeypatch.setattr("hogli_commands.git_signing.click.confirm", confirm)
        configure_git = mock.Mock()
        monkeypatch.setattr(setup, "_configure_git", configure_git)

        if configured:
            setup.run()
        else:
            with pytest.raises(click.Abort):
                setup.run()

        assert configure_git.called == configured


class TestForwardsAgentToDevboxes:
    @pytest.mark.parametrize(
        "ssh_config, expected",
        [
            ("# --- START-CODER ---\nHost coder.*\n\tForwardAgent yes\n# --- END-CODER ---\n", True),
            ("# --- START-CODER ---\nHost coder.*\n\tUser coder\n# --- END-CODER ---\n", False),
            ("Host *\n\tForwardAgent yes\n", False),
            (None, False),
        ],
        ids=["coder_block_forwards", "coder_block_without_forwarding", "forwarding_outside_coder_block", "no_config"],
    )
    def test_detects_agent_forwarding_in_the_coder_block(
        self, tmp_path: Path, ssh_config: str | None, expected: bool
    ) -> None:
        config_path = tmp_path / "config"
        if ssh_config is not None:
            config_path.write_text(ssh_config)

        assert forwards_agent_to_devboxes(config_path) == expected


class TestPreviousKeyAdvice:
    @pytest.mark.parametrize(
        "uses_devbox, targets, tells_to_remove",
        [(True, [None], False), (False, [Path("/repo")], False), (False, [None], True)],
        ids=["devbox", "repo_only", "global"],
    )
    def test_previous_key_is_removed_only_when_nothing_signs_with_it(
        self, capsys: pytest.CaptureFixture[str], uses_devbox: bool, targets: list[Path | None], tells_to_remove: bool
    ) -> None:
        setup = SecureEnclaveSigningSetup(use_global=True, repos=())
        setup.uses_devbox = uses_devbox
        setup.targets = targets

        setup._print_undo_steps()

        assert ("Remove your previous signing key" in capsys.readouterr().out) == tells_to_remove


def sk_ecdsa_public_key(point: bytes) -> str:
    fields = [b"sk-ecdsa-sha2-nistp256@openssh.com", b"nistp256", point, b"ssh:"]
    return base64.b64encode(b"".join(struct.pack(">I", len(field)) + field for field in fields)).decode()


def sc_auth_row(point: bytes, label: str) -> str:
    return f"p-256-ne {hashlib.sha1(point).hexdigest().upper()} none {label} {label} 26/11/27, 09:38 YES"


POINTS = [bytes([4]) + bytes([n]) * 64 for n in (1, 2, 3)]
KEYS = [sk_ecdsa_public_key(point) for point in POINTS]


class TestExportKeys:
    # Mirrors ssh-keygen -K with Apple's provider: the PIN prompt reads stdin when there is no
    # terminal, and every key goes to the same file behind an overwrite prompt.
    FAKE_SSH_KEYGEN = """\
import os
import sys
import signal
from pathlib import Path

sys.stderr.write("Enter PIN for authenticator: ")
sys.stderr.flush()
sys.stdin.readline()
blobs = Path(os.environ["FAKE_SECURE_ENCLAVE_KEYS_FILE"]).read_text().split()
for blob in blobs:
    path = Path("id_ecdsa_sk_rk")
    if path.exists():
        print(f"{path} already exists.")
        print("Overwrite (y/n)? ", end="", flush=True)
        if os.environ.get("FAKE_PROVIDER_HANGS"):
            signal.pause()
        if not sys.stdin.readline().startswith("y"):
            sys.exit(1)
    path.write_text(f"handle {blob}\\n")
    Path(f"{path}.pub").write_text(f"sk-ecdsa-sha2-nistp256@openssh.com {blob} ssh:\\n")
    print(f"Saved ECDSA-SK key to {path}", flush=True)
# Before the first key exists, the provider has nothing to export.
sys.exit(0 if blobs else 1)
"""
    FAKE_SC_AUTH = """\
#!/bin/sh
case "$1" in
    list-ctk-identities) cat "$FAKE_SC_AUTH_IDENTITIES" ;;
    create-ctk-identity) printf ' %s' "$FAKE_CREATED_KEY" >> "$FAKE_SECURE_ENCLAVE_KEYS_FILE" ;;
esac
"""

    @pytest.fixture
    def keys_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        ssh_keygen = tmp_path / "ssh-keygen"
        ssh_keygen.write_text(f"#!{sys.executable}\n{self.FAKE_SSH_KEYGEN}")
        ssh_keygen.chmod(0o755)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "sc_auth").write_text(self.FAKE_SC_AUTH)
        (bin_dir / "sc_auth").chmod(0o755)
        monkeypatch.setattr("hogli_commands.git_signing.SSH_KEYGEN", ssh_keygen)
        monkeypatch.setattr("hogli_commands.git_signing.SSH_DIR", tmp_path / "ssh")
        monkeypatch.setattr("hogli_commands.git_signing.KEY_PATH", tmp_path / "ssh" / "id_ecdsa_sk_git_signing")
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        keys_file = tmp_path / "secure-enclave-keys"
        keys_file.write_text("")
        monkeypatch.setenv("FAKE_SECURE_ENCLAVE_KEYS_FILE", str(keys_file))
        return keys_file

    @pytest.fixture
    def export_dir(self, tmp_path: Path) -> Path:
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        return export_dir

    @pytest.mark.parametrize("blobs", [[], KEYS[:1], KEYS])
    def test_exports_every_secure_enclave_key(self, keys_file: Path, export_dir: Path, blobs: list[str]) -> None:
        keys_file.write_text(" ".join(blobs))

        handles = SecureEnclaveSigningSetup(use_global=True, repos=())._export_keys(export_dir)

        assert {identity: handle.read_text() for identity, handle in handles.items()} == {
            f"sk-ecdsa-sha2-nistp256@openssh.com {blob}": f"handle {blob}\n" for blob in blobs
        }

    def test_interrupt_stops_ssh_keygen(
        self, keys_file: Path, export_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keys_file.write_text(" ".join(KEYS[:2]))
        monkeypatch.setenv("FAKE_PROVIDER_HANGS", "1")
        monkeypatch.setattr("hogli_commands.git_signing.move_exported_handle", mock.Mock(side_effect=KeyboardInterrupt))
        started: list[subprocess.Popen[bytes]] = []
        real_popen = subprocess.Popen

        def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            started.append(real_popen(*args, **kwargs))
            return started[-1]

        monkeypatch.setattr("hogli_commands.git_signing.subprocess.Popen", recording_popen)

        with pytest.raises(KeyboardInterrupt):
            SecureEnclaveSigningSetup(use_global=True, repos=())._export_keys(export_dir)

        try:
            assert started[0].returncode is not None
        finally:
            if started[0].returncode is None:
                started[0].kill()
                started[0].wait()

    @pytest.mark.parametrize(
        "on_mac, labels, installed",
        [
            # A failed run left KEYS[1] behind, so the rerun uses it and creates nothing.
            (KEYS[:2], {0: "other-tool", 1: "git-signing"}, KEYS[1]),
            ([KEYS[0]], {0: "other-tool"}, KEYS[2]),
        ],
    )
    def test_reuses_a_key_left_by_a_failed_run(
        self,
        keys_file: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        on_mac: list[str],
        labels: dict[int, str],
        installed: str,
    ) -> None:
        keys_file.write_text(" ".join(on_mac))
        identities = tmp_path / "identities"
        identities.write_text(
            "Key Type Public Key Hash Prot Label Common Name Email Address Valid To Valid\n"
            + "".join(f"{sc_auth_row(POINTS[index], label)}\n" for index, label in labels.items())
        )
        monkeypatch.setenv("FAKE_SC_AUTH_IDENTITIES", str(identities))
        monkeypatch.setenv("FAKE_CREATED_KEY", KEYS[2])

        SecureEnclaveSigningSetup(use_global=True, repos=())._create_and_install_key()

        assert (tmp_path / "ssh" / "id_ecdsa_sk_git_signing").read_text() == f"handle {installed}\n"
