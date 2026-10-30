from __future__ import annotations

import subprocess
from pathlib import Path

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
