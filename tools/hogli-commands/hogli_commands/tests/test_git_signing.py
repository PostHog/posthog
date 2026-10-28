from __future__ import annotations

from pathlib import Path

import pytest

import click
from hogli_commands.git_signing import pick_new_key, public_key_identity


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
