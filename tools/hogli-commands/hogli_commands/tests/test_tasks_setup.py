from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import click
from click.testing import CliRunner, Result
from hogli_commands import env_file, posthog_auth, tasks_setup

_DNS = "laptop.tail1234.ts.net"
_MODAL_ID = "ak-modalidsecretvalue1"
_MODAL_SECRET = "as-modalsecretsecretvalue2"
_OLD_TOKEN = "phe_oldtokensecretvalue3"
_NEW_TOKEN = "phe_newtokensecretvalue4"
_SECRETS = (_MODAL_ID, _MODAL_SECRET, _OLD_TOKEN, _NEW_TOKEN)
_EXAMPLE = "SANDBOX_PROVIDER=docker\nSANDBOX_MCP_URL=http://host.docker.internal:8787/mcp\n"
_CONFIGURED = (
    f"SANDBOX_PROVIDER=MODAL_DOCKER\nMODAL_TOKEN_ID={_MODAL_ID}\nMODAL_TOKEN_SECRET={_MODAL_SECRET}\n"
    "SANDBOX_AI_GATEWAY_URL=https://gateway.us.posthog.com\nSANDBOX_AI_GATEWAY_PRODUCTS=posthog_code\n"
    f"SANDBOX_AI_GATEWAY_DEV_TOKEN={_OLD_TOKEN}\nSANDBOX_API_URL=https://{_DNS}\n"
    f"SANDBOX_MCP_URL=https://{_DNS}:10000/mcp\n"
)


@dataclass
class Sandbox:
    root: Path
    op_available: bool = True
    token_expires_in: timedelta = timedelta(days=5)
    terminal: bool = False
    minted: list[int | None] = field(default_factory=list)

    def write(self, name: str, text: str) -> None:
        (self.root / name).write_text(text)

    def read(self, name: str) -> str:
        return env_file.read(self.root / name)

    def snapshot(self) -> dict[str, str]:
        return {path.name: path.read_text() for path in sorted(self.root.iterdir())}

    def run(self, *args: str, answer: str | None = None) -> Result:
        return CliRunner(mix_stderr=False).invoke(tasks_setup.tasks_setup, list(args), input=answer)


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    box = Sandbox(root=tmp_path)
    box.write(".env.example", _EXAMPLE)

    def op_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[:2] == ["/bin/op", "read"], f"unexpected subprocess: {command}"
        value = {"MODAL_TOKEN_ID": _MODAL_ID, "MODAL_TOKEN_SECRET": _MODAL_SECRET}[command[-1].rsplit("/", 1)[1]]
        return subprocess.CompletedProcess(command, 0 if box.op_available else 1, value if box.op_available else "")

    def token_status(_host: str, token: str) -> dict[str, Any]:
        expires = datetime.now(UTC) + (timedelta(days=7) if token == _NEW_TOKEN else box.token_expires_in)
        return {"status": "live", "expires_at": expires.isoformat()}

    def mint_token(_host: str, *, cap_usd: float | None, ttl_seconds: int | None) -> dict[str, Any]:
        box.minted.append(ttl_seconds)
        return {"token": _NEW_TOKEN}

    monkeypatch.setattr(tasks_setup, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(tasks_setup.shutil, "which", lambda name: "/bin/op" if name == "op" else None)
    monkeypatch.setattr(tasks_setup.subprocess, "run", op_run)
    monkeypatch.setattr(tasks_setup.gateway, "token_status", token_status)
    monkeypatch.setattr(tasks_setup.gateway, "mint_token", mint_token)
    monkeypatch.setattr(tasks_setup.coder, "tailscale_self_dns", lambda: _DNS)
    monkeypatch.setattr(tasks_setup, "_terminal", lambda: box.terminal)
    monkeypatch.setattr(tasks_setup, "_today", lambda: "20261127")
    for key in (*tasks_setup.LEGACY_KEYS, "SANDBOX_PROVIDER", "SANDBOX_API_URL"):
        monkeypatch.delenv(key, raising=False)
    return box


def _build(
    sandbox: Sandbox, *, funnel_host: str | None = None, environ: dict[str, str] | None = None
) -> tasks_setup.Plan:
    texts = {name: sandbox.read(name) for name in (".env", ".env.local")}
    return tasks_setup.build_plan(texts, _EXAMPLE, environ or {}, funnel_host, False, False)


def _plan(sandbox: Sandbox, *, funnel_host: str | None = None) -> dict[tuple[str, str], tasks_setup.Row]:
    return {(row.key, row.file): row for row in _build(sandbox, funnel_host=funnel_host).rows}


@pytest.mark.parametrize(
    "env,env_local,key,expected",
    [
        ("", "", "SANDBOX_PROVIDER", (".env.local", "add", False)),
        ("SANDBOX_PROVIDER=MODAL_DOCKER\n", "", "SANDBOX_PROVIDER", (".env", "keep", False)),
        ("SANDBOX_PROVIDER=docker\n", "", "SANDBOX_PROVIDER", (".env", "update", False)),
        ("SANDBOX_PROVIDER=docker  # default\n", "", "SANDBOX_PROVIDER", (".env", "update", False)),
        ("SANDBOX_PROVIDER=modal\n", "", "SANDBOX_PROVIDER", (".env", "update", True)),
        ("SANDBOX_PROVIDER=\n", "", "SANDBOX_PROVIDER", (".env", "update", False)),
        ("", "SANDBOX_PROVIDER=modal\n", "SANDBOX_PROVIDER", (".env.local", "update", True)),
        ("SANDBOX_PROVIDER=docker\n", "SANDBOX_PROVIDER=modal\n", "SANDBOX_PROVIDER", (".env", "update", False)),
        ("SANDBOX_AI_GATEWAY_PRODUCTS=slack_app\n", "", "SANDBOX_AI_GATEWAY_PRODUCTS", (".env", "update", False)),
        ("", "SANDBOX_API_URL=https://old.ngrok.app\n", "SANDBOX_API_URL", (".env.local", "update", True)),
        ("SANDBOX_AI_GATEWAY_DEV_TOKEN=phe_expired\n", "", "SANDBOX_AI_GATEWAY_DEV_TOKEN", (".env", "update", False)),
        ("SANDBOX_AI_GATEWAY_DEV_TOKEN=sk-other\n", "", "SANDBOX_AI_GATEWAY_DEV_TOKEN", (".env", "update", True)),
        ("SANDBOX_LLM_GATEWAY_URL=http://localhost:3308\n", "", "SANDBOX_LLM_GATEWAY_URL", (".env", "disable", False)),
        (
            "",
            "SANDBOX_AI_GATEWAY_WORKER_URL=http://host.docker.internal:3308\n",
            "SANDBOX_AI_GATEWAY_WORKER_URL",
            (".env.local", "disable", False),
        ),
    ],
)
def test_plan_writes_where_the_key_wins_and_flags_overwrites_of_custom_values(
    sandbox: Sandbox, env: str, env_local: str, key: str, expected: tuple[str, str, bool]
) -> None:
    sandbox.token_expires_in = timedelta(hours=1)
    sandbox.write(".env", env)
    sandbox.write(".env.local", env_local)

    row = next(row for (row_key, _file), row in _plan(sandbox).items() if row_key == key)

    assert (row.file, row.action, row.needs_force) == expected


def test_a_remote_worker_url_is_left_alone(sandbox: Sandbox) -> None:
    sandbox.write(".env", "SANDBOX_AI_GATEWAY_WORKER_URL=https://gateway.internal.example.com\n")

    assert "SANDBOX_AI_GATEWAY_WORKER_URL" not in {key for key, _file in _plan(sandbox)}


def test_products_append_posthog_code_and_keep_existing_entries(sandbox: Sandbox) -> None:
    sandbox.write(".env", "SANDBOX_AI_GATEWAY_PRODUCTS=slack_app\n")

    assert _plan(sandbox)["SANDBOX_AI_GATEWAY_PRODUCTS", ".env"].new == "slack_app,posthog_code"


def test_funnel_host_override_wins_over_tailscale(sandbox: Sandbox) -> None:
    rows = _plan(sandbox, funnel_host="other.tail1234.ts.net")

    assert rows["SANDBOX_MCP_URL", ".env.local"].new == "https://other.tail1234.ts.net:10000/mcp"


@pytest.mark.parametrize(
    "env", ["SANDBOX_PROVIDER=docker\nSANDBOX_LLM_GATEWAY_URL=http://localhost:3308\n", _CONFIGURED]
)
def test_dry_run_writes_nothing_and_mints_nothing(sandbox: Sandbox, env: str) -> None:
    sandbox.write(".env", env)
    before = sandbox.snapshot()

    result = sandbox.run("--dry-run", "--yes", "--force", "--non-interactive")

    assert result.exit_code == 0, result.output
    assert result.stdout.rstrip().endswith("[DRY-RUN] Nothing changed.")
    assert sandbox.snapshot() == before
    assert sandbox.minted == []


def test_apply_preserves_every_other_line_byte_for_byte(sandbox: Sandbox) -> None:
    original = (
        "# keep me\r\nexport OTHER='a b'\r\nSANDBOX_PROVIDER=docker\r\n\r\n"
        "SANDBOX_LLM_GATEWAY_URL=http://localhost:3308\r\nTRAILING=1"
    )
    sandbox.write(".env", original)

    result = sandbox.run("--yes")

    assert result.exit_code == 0, result.output
    assert sandbox.read(".env") == (
        "# keep me\r\nexport OTHER='a b'\r\nSANDBOX_PROVIDER=MODAL_DOCKER\r\n\r\n"
        "# disabled by hogli tasks:setup: SANDBOX_LLM_GATEWAY_URL=http://localhost:3308\r\nTRAILING=1"
    )


def test_new_keys_are_appended_to_env_local_under_a_header(sandbox: Sandbox) -> None:
    sandbox.write(".env.local", "MINE=1\n")

    sandbox.run("--yes")

    assert sandbox.read(".env.local") == (
        f"MINE=1\n\n{tasks_setup.HEADER}\nSANDBOX_PROVIDER=MODAL_DOCKER\nMODAL_TOKEN_ID={_MODAL_ID}\n"
        f"MODAL_TOKEN_SECRET={_MODAL_SECRET}\nSANDBOX_AI_GATEWAY_URL=https://gateway.us.posthog.com\n"
        f"SANDBOX_AI_GATEWAY_PRODUCTS=posthog_code\nSANDBOX_API_URL=https://{_DNS}\n"
        f"SANDBOX_MCP_URL=https://{_DNS}:10000/mcp\nSANDBOX_AI_GATEWAY_DEV_TOKEN={_NEW_TOKEN}\n"
    )
    assert sandbox.minted == [7 * 24 * 60 * 60]


def test_backup_is_taken_once_from_the_original(sandbox: Sandbox) -> None:
    sandbox.write(".env", "SANDBOX_PROVIDER=docker\n")
    sandbox.run("--yes")
    sandbox.write(".env", sandbox.read(".env") + "SANDBOX_LLM_GATEWAY_URL=http://localhost:3308\n")

    sandbox.run("--yes")

    backups = [name for name in sandbox.snapshot() if name.startswith(".env.bak-tasks-setup-")]
    assert len(backups) == 1
    assert sandbox.read(backups[0]) == "SANDBOX_PROVIDER=docker\n"


def test_second_run_is_a_no_op(sandbox: Sandbox) -> None:
    sandbox.write(".env", "SANDBOX_PROVIDER=docker\n")
    sandbox.run("--yes")
    before = sandbox.snapshot()

    result = sandbox.run("--non-interactive")

    assert result.exit_code == 0, result.output
    assert "Nothing to change." in result.stdout
    assert sandbox.snapshot() == before


@pytest.mark.parametrize("args", [("--dry-run",), ("--yes",), ("--yes", "--refresh-token")])
def test_secrets_never_reach_the_output(sandbox: Sandbox, args: tuple[str, ...]) -> None:
    sandbox.write(".env", f"MODAL_TOKEN_ID=ak-stale\nSANDBOX_AI_GATEWAY_DEV_TOKEN={_OLD_TOKEN}\n")

    result = sandbox.run(*args, "--force")

    assert result.exit_code == 0, result.output
    assert not [secret for secret in _SECRETS if secret in result.stdout + result.stderr]


@pytest.mark.parametrize(
    "args,terminal,message",
    [
        (("--non-interactive",), False, "--yes"),
        ((), False, "--yes"),
        (("--yes",), False, "--force"),
        (("--yes", "--non-interactive"), True, "--force"),
    ],
)
def test_refuses_without_consent_and_changes_nothing(
    sandbox: Sandbox, args: tuple[str, ...], terminal: bool, message: str
) -> None:
    sandbox.terminal = terminal
    sandbox.write(".env", "SANDBOX_PROVIDER=modal\n")
    before = sandbox.snapshot()

    result = sandbox.run(*args)

    assert result.exit_code == 2
    assert message in result.stderr
    assert sandbox.snapshot() == before


def test_terminal_prompt_declined_changes_nothing(sandbox: Sandbox) -> None:
    sandbox.terminal = True
    sandbox.write(".env", "SANDBOX_PROVIDER=modal\n")
    before = sandbox.snapshot()

    result = sandbox.run(answer="n\n")

    assert result.exit_code == 1
    assert "replacing your own values for SANDBOX_PROVIDER in .env" in result.stdout
    assert sandbox.snapshot() == before


@pytest.mark.parametrize("args,exit_code", [(("--yes",), 0), (("--yes", "--non-interactive"), 1)])
def test_missing_op_leaves_modal_keys_as_a_remaining_step(
    sandbox: Sandbox, args: tuple[str, ...], exit_code: int
) -> None:
    sandbox.op_available = False

    result = sandbox.run(*args)

    assert result.exit_code == exit_code, result.output
    assert tasks_setup.MODAL_STEP in result.stdout
    assert "MODAL_TOKEN_ID" not in env_file.values(sandbox.read(".env.local"))


def test_non_interactive_lists_the_token_mint_instead_of_opening_a_browser(sandbox: Sandbox) -> None:
    sandbox.write(".env", _CONFIGURED)
    sandbox.token_expires_in = timedelta(hours=3)

    result = sandbox.run("--non-interactive")

    assert result.exit_code == 1
    assert "hogli tasks:setup --refresh-token" in result.stdout
    assert sandbox.minted == []


@pytest.mark.parametrize(
    "error", [posthog_auth.AuthError("browser approval timed out"), click.ClickException("gateway down")]
)
def test_a_failed_mint_still_writes_the_rest(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(tasks_setup.gateway, "mint_token", fail)

    result = sandbox.run("--yes")

    assert result.exit_code == 0, result.output
    written = env_file.values(sandbox.read(".env.local"))
    assert written["SANDBOX_PROVIDER"] == ["MODAL_DOCKER"]
    assert "SANDBOX_AI_GATEWAY_DEV_TOKEN" not in written
    assert "hogli tasks:setup --refresh-token" in result.stdout


@pytest.mark.parametrize("value", ["https://laptop.ts.net", "laptop", "bad host.ts.net"])
def test_funnel_host_rejects_anything_but_a_dns_name(sandbox: Sandbox, value: str) -> None:
    result = sandbox.run("--dry-run", "--funnel-host", value)

    assert result.exit_code == 2


def test_unsafe_merged_value_becomes_a_manual_step_instead_of_a_write(sandbox: Sandbox) -> None:
    sandbox.write(".env.local", "SANDBOX_AI_GATEWAY_PRODUCTS='slack_app $HOME'\n")

    plan = _build(sandbox)

    assert "SANDBOX_AI_GATEWAY_PRODUCTS" not in {row.key for row in plan.rows}
    assert "SANDBOX_AI_GATEWAY_PRODUCTS" in plan.remaining["unsafe:SANDBOX_AI_GATEWAY_PRODUCTS"]


def test_a_legacy_key_still_exported_after_disabling_asks_to_reactivate_flox(sandbox: Sandbox) -> None:
    sandbox.write(".env", f"{tasks_setup.DISABLE_MARKER}SANDBOX_LLM_GATEWAY_URL=http://localhost:3308\n")

    plan = _build(sandbox, environ={"SANDBOX_LLM_GATEWAY_URL": "http://localhost:3308"})

    assert "re-activate flox" in plan.remaining["shell:SANDBOX_LLM_GATEWAY_URL"]


def test_writing_through_a_symlinked_env_file_updates_the_target(sandbox: Sandbox, tmp_path_factory: Any) -> None:
    target = tmp_path_factory.mktemp("main") / ".env.local"
    target.write_text("MINE=1\n")
    (sandbox.root / ".env.local").symlink_to(target)

    sandbox.run("--yes")

    assert (sandbox.root / ".env.local").is_symlink()
    assert env_file.values(target.read_text())["SANDBOX_PROVIDER"] == ["MODAL_DOCKER"]


def test_keys_added_on_a_later_run_reuse_the_existing_header(sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_setup.coder, "tailscale_self_dns", lambda: None)
    sandbox.run("--yes")
    monkeypatch.setattr(tasks_setup.coder, "tailscale_self_dns", lambda: _DNS)

    sandbox.run("--yes")

    text = sandbox.read(".env.local")
    assert text.count(tasks_setup.HEADER) == 1
    assert text.endswith(f"SANDBOX_API_URL=https://{_DNS}\nSANDBOX_MCP_URL=https://{_DNS}:10000/mcp\n")
