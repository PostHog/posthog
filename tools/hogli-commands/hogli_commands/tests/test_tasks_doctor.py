import json
from collections.abc import Mapping
from types import SimpleNamespace

import pytest

from click.testing import CliRunner
from hogli_commands import tasks_doctor
from hogli_commands.tasks_doctor import (
    Check,
    EnvLayers,
    EnvRequirement,
    Status,
    check_dotenv_loaded,
    check_env_requirement,
    check_modal_auth,
    check_modal_reach,
    check_modal_tunnel,
    check_modal_urls,
    check_sandbox_provider,
    funnel_fix,
    funnel_listeners,
    load_env_layers,
    modal_targets,
    parse_env_text,
    resolve_env_key,
    sandbox_backend,
    sandbox_probe_script,
    sandbox_url,
    stale_env_files,
    tunnel_problems,
    unreachable_targets,
    validate_github_client_id,
    validate_pem,
    validate_sandbox_mcp_url,
)

PEM = "-----BEGIN RSA PRIVATE KEY-----\\nabc\\n-----END RSA PRIVATE KEY-----"


def layers(environ: Mapping[str, str] | None = None, **files: Mapping[str, str]) -> EnvLayers:
    names = {"dotenv": ".env", "local": ".env.local", "development": ".env.development"}
    return EnvLayers(
        files=tuple((names[alias], values) for alias, values in files.items()),
        environ=environ or {},
        secret_marker="op://",
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("KEY=value", {"KEY": "value"}),
        ('KEY="quoted value"', {"KEY": "quoted value"}),
        ("KEY='single'", {"KEY": "single"}),
        ("export KEY=value", {"KEY": "value"}),
        ("# KEY=value\n\nOTHER=1", {"OTHER": "1"}),
        ("KEY=a=b", {"KEY": "a=b"}),
        ("not a line", {}),
    ],
)
def test_parse_env_text(text: str, expected: dict[str, str]) -> None:
    assert parse_env_text(text) == expected


@pytest.mark.parametrize(
    "env_layers, expected_value, expected_source",
    [
        (layers(dotenv={"KEY": "a"}, local={"KEY": "b"}), "a", ".env"),
        (layers(local={"KEY": "b"}, development={"KEY": "c"}), "b", ".env.local"),
        (layers({"KEY": "b"}, dotenv={"KEY": "a"}, local={"KEY": "b"}), "a", ".env"),
        (layers({"KEY": "shell"}, dotenv={"KEY": "a"}), "shell", "shell"),
        (layers(local={"KEY": "op://vault/item"}), None, None),
        (layers(), None, None),
    ],
    ids=[
        "dotenv_beats_local",
        "local_beats_development",
        "hogli_loaded_local_does_not_hide_dotenv",
        "shell_override",
        "secret_reference_only",
        "unset",
    ],
)
def test_resolve_env_key_value_and_source(
    env_layers: EnvLayers, expected_value: str | None, expected_source: str | None
) -> None:
    resolution = resolve_env_key("KEY", env_layers)
    assert (resolution.value, resolution.source) == (expected_value, expected_source)


@pytest.mark.parametrize(
    "env_layers, expected_conflicts",
    [
        (layers(dotenv={"KEY": "a"}, local={"KEY": "b"}), (".env", ".env.local")),
        (layers(dotenv={"KEY": "a"}, local={"KEY": "a"}), ()),
        (layers(dotenv={"KEY": "a"}, local={"KEY": "op://vault/item"}), ()),
    ],
    ids=["different_values", "same_values", "secret_reference_ignored"],
)
def test_resolve_env_key_conflicts(env_layers: EnvLayers, expected_conflicts: tuple[str, ...]) -> None:
    assert resolve_env_key("KEY", env_layers).conflicting_sources == expected_conflicts


REQUIRED = EnvRequirement("KEY", Status.ERROR, "fix it", validate_pem)
OPTIONAL = EnvRequirement("KEY", Status.ERROR, "fix it", optional=True)


@pytest.mark.parametrize(
    "requirement, env_layers, expected_status",
    [
        (REQUIRED, layers(), Status.ERROR),
        (OPTIONAL, layers(), Status.OK),
        (REQUIRED, layers(local={"KEY": PEM}), Status.OK),
        (REQUIRED, layers(local={"KEY": "not-a-key"}), Status.ERROR),
        (REQUIRED, layers(dotenv={"KEY": PEM}, local={"KEY": PEM + "x"}), Status.WARN),
        (REQUIRED, layers(local={"KEY": "op://vault/item"}), Status.OK),
        (REQUIRED, layers({"KEY": PEM}), Status.OK),
    ],
    ids=["missing", "optional_missing", "valid", "invalid", "conflict", "secret_reference", "shell_only"],
)
def test_check_env_requirement_status(
    requirement: EnvRequirement, env_layers: EnvLayers, expected_status: Status
) -> None:
    assert check_env_requirement(requirement, env_layers).status == expected_status


@pytest.mark.parametrize(
    "env_layers, expected_status",
    [
        (layers(), Status.WARN),
        (layers(local={"SANDBOX_PROVIDER": "docker"}), Status.OK),
        (layers(local={"SANDBOX_PROVIDER": "DOCKER"}), Status.WARN),
        (layers(local={"SANDBOX_PROVIDER": "hogland"}), Status.WARN),
        (layers(local={"SANDBOX_PROVIDER": "MODAL_DOCKER"}), Status.OK),
        (layers(local={"SANDBOX_PROVIDER": "modal"}), Status.OK),
        (layers(dotenv={"SANDBOX_PROVIDER": "docker"}, local={"SANDBOX_PROVIDER": "modal"}), Status.WARN),
    ],
    ids=[
        "unset_goes_to_production_modal",
        "docker",
        "uppercase_docker_goes_to_modal",
        "hogland",
        "modal_docker",
        "modal",
        "conflict",
    ],
)
def test_check_sandbox_provider(env_layers: EnvLayers, expected_status: Status) -> None:
    resolution = resolve_env_key("SANDBOX_PROVIDER", env_layers)
    assert check_sandbox_provider(resolution, sandbox_backend(resolution.value)).status == expected_status


@pytest.mark.parametrize(
    "environ, expected",
    [
        ({"KEY": '"a"'}, "a"),
        ({"KEY": "a"}, "a"),
    ],
)
def test_load_env_layers_unquotes_environ(tmp_path, environ: dict[str, str], expected: str) -> None:
    assert load_env_layers([tmp_path / ".env"], environ, "op://").environ["KEY"] == expected


def test_sandbox_probe_script_runs_probes_in_parallel() -> None:
    script = sandbox_probe_script([("llm-gateway", "http://a/_liveness"), ("mcp", "http://b/health")])
    assert (script.count(" &"), script.endswith("wait")) == (2, True)


@pytest.mark.parametrize(
    "env_layers, expected_status",
    [
        (layers({"A": "1", "B": "2"}, dotenv={"A": "1", "B": "2"}), Status.OK),
        (layers({"A": "1"}, dotenv={"A": "1", "B": "2"}), Status.WARN),
        (layers({}, dotenv={"A": "op://vault/item"}), Status.OK),
        (layers({}), Status.OK),
    ],
    ids=["loaded", "missing_key", "secret_reference_ignored", "no_dotenv"],
)
def test_check_dotenv_loaded(env_layers: EnvLayers, expected_status: Status) -> None:
    assert check_dotenv_loaded(env_layers).status == expected_status


@pytest.mark.parametrize(
    "validator, value, valid",
    [
        (validate_pem, PEM, True),
        (validate_pem, "secret", False),
        (validate_github_client_id, "Iv23abcdef", True),
        (validate_github_client_id, "123456", False),
        (validate_sandbox_mcp_url, "http://host.docker.internal:8787/mcp", True),
        (validate_sandbox_mcp_url, "http://localhost:8787/mcp", False),
        (validate_sandbox_mcp_url, "not a url", False),
    ],
)
def test_validators(validator, value: str, valid: bool) -> None:
    assert (validator(value) is None) == valid


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://localhost:3308", "http://host.docker.internal:3308"),
        ("http://127.0.0.1:8787/mcp", "http://host.docker.internal:8787/mcp"),
        ("https://gateway.us.posthog.com", "https://gateway.us.posthog.com"),
    ],
)
def test_sandbox_url(url: str, expected: str) -> None:
    assert sandbox_url(url) == expected


@pytest.mark.parametrize(
    "output, expected",
    [
        ("llm-gateway 200\n\nmcp 200\n", []),
        ("llm-gateway 000\n\nmcp 200\n", ["llm-gateway (http 000)"]),
        ("llm-gateway\nmcp 503\n", ["llm-gateway (no response)", "mcp (http 503)"]),
    ],
)
def test_unreachable_targets(output: str, expected: list[str]) -> None:
    assert unreachable_targets(output, ["llm-gateway", "mcp"]) == expected


@pytest.mark.parametrize(
    "started_at, expected",
    [
        (100.0, [".env.local"]),
        (300.0, []),
        (50.0, [".env", ".env.local"]),
    ],
)
def test_stale_env_files(started_at: float, expected: list[str]) -> None:
    assert stale_env_files(started_at, {".env": 90.0, ".env.local": 200.0}) == expected


@pytest.mark.parametrize(
    "results, expected_exit_code",
    [
        ([Check("a", Status.OK, "fine")], 0),
        ([Check("a", Status.WARN, "meh", "fix")], 0),
        ([Check("a", Status.ERROR, "broken", "fix")], 1),
    ],
)
def test_cli_json_output_and_exit_code(monkeypatch, results: list[Check], expected_exit_code: int) -> None:
    monkeypatch.setattr(tasks_doctor, "run_all_checks", lambda repo_root, include_database: results)
    outcome = CliRunner().invoke(tasks_doctor.tasks_doctor, ["--json", "--skip-db"])
    assert (outcome.exit_code, json.loads(outcome.output)) == (
        expected_exit_code,
        [result.to_json() for result in results],
    )


PUBLIC_ENVIRON = {
    "SANDBOX_API_URL": "https://api.example.ngrok.app",
    "SANDBOX_LLM_GATEWAY_URL": "https://gateway.example.ngrok.app",
    "SANDBOX_MCP_URL": "https://mcp.example.ngrok.app/mcp",
}


@pytest.mark.parametrize(
    "environ, expected_status",
    [
        (PUBLIC_ENVIRON, Status.OK),
        ({**PUBLIC_ENVIRON, "SANDBOX_MCP_URL": "http://host.docker.internal:8787/mcp"}, Status.ERROR),
        ({key: value for key, value in PUBLIC_ENVIRON.items() if key != "SANDBOX_MCP_URL"}, Status.ERROR),
        ({**PUBLIC_ENVIRON, "SANDBOX_API_URL": "", "SITE_URL": "http://localhost:8010"}, Status.ERROR),
        ({key: value for key, value in PUBLIC_ENVIRON.items() if key != "SANDBOX_LLM_GATEWAY_URL"}, Status.ERROR),
    ],
    ids=["all_public", "mcp_docker_host", "mcp_falls_back_to_local", "api_falls_back_to_localhost", "gateway_unset"],
)
def test_check_modal_urls(environ: dict[str, str], expected_status: Status) -> None:
    assert check_modal_urls(modal_targets(environ)).status == expected_status


def test_modal_targets_health_urls() -> None:
    assert modal_targets(PUBLIC_ENVIRON) == [
        ("api", "https://api.example.ngrok.app/_livez"),
        ("llm-gateway", "https://gateway.example.ngrok.app/_liveness"),
        ("mcp", "https://mcp.example.ngrok.app/health"),
    ]


@pytest.mark.parametrize(
    "answering, expected_status",
    [
        ({"api", "llm-gateway", "mcp"}, Status.OK),
        ({"api", "mcp"}, Status.ERROR),
        ({"api", "llm-gateway"}, Status.WARN),
        (set(), Status.ERROR),
    ],
)
def test_check_modal_reach(monkeypatch, answering: set[str], expected_status: Status) -> None:
    targets = modal_targets(PUBLIC_ENVIRON)
    urls_answering = {url for name, url in targets if name in answering}
    monkeypatch.setattr(tasks_doctor, "http_ok", lambda url, timeout_seconds: url in urls_answering)
    assert check_modal_reach(targets).status == expected_status


@pytest.mark.parametrize(
    "public_ips, relay_answers, expected_status",
    [
        (["203.0.113.1"], True, Status.OK),
        ([], True, Status.ERROR),
        (["203.0.113.1"], False, Status.ERROR),
    ],
    ids=["relay_answers", "no_public_dns_record", "relay_silent"],
)
def test_check_modal_reach_funnel_goes_through_public_relay(
    monkeypatch, public_ips: list[str], relay_answers: bool, expected_status: Status
) -> None:
    from products.posthog_ai.eval_harness.harness import tunnels

    monkeypatch.setattr(tasks_doctor, "http_ok", lambda url, timeout_seconds: True)
    monkeypatch.setattr(tunnels, "_public_ips", lambda host: public_ips)
    monkeypatch.setattr(tunnels, "_relay_answers", lambda address, host, port: relay_answers)
    assert check_modal_reach(FUNNEL_TARGETS).status == expected_status


@pytest.mark.parametrize(
    "environ, expected_mcp_port",
    [
        ({"SANDBOX_MCP_URL": "https://laptop.example.ts.net:10000/mcp"}, 8787),
        ({"MCP_SERVER_URL": "http://localhost:9999/mcp"}, 9999),
    ],
    ids=["public_sandbox_url_ignored", "local_server_url_used"],
)
def test_funnel_local_ports_reads_local_mcp_port(environ: dict[str, str], expected_mcp_port: int) -> None:
    assert tasks_doctor.funnel_local_ports(environ)["mcp"] == expected_mcp_port


def test_check_modal_reach_skips_without_public_urls() -> None:
    assert check_modal_reach([("api", "http://localhost:8010/_livez")]).status == Status.SKIPPED


TOKENS = {"MODAL_TOKEN_ID": "ak-test", "MODAL_TOKEN_SECRET": "as-test"}


@pytest.mark.parametrize(
    "environ, config_exists, return_code, expected_status",
    [
        ({}, False, 0, Status.ERROR),
        (TOKENS, False, 0, Status.OK),
        ({}, True, 0, Status.OK),
        (TOKENS, False, 1, Status.ERROR),
    ],
    ids=["no_credentials", "env_tokens_accepted", "config_file_accepted", "token_rejected"],
)
def test_check_modal_auth(
    monkeypatch, tmp_path, environ: dict[str, str], config_exists: bool, return_code: int, expected_status: Status
) -> None:
    config_path = tmp_path / ".modal.toml"
    if config_exists:
        config_path.write_text("[default]\n")
    monkeypatch.setattr(tasks_doctor, "MODAL_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        tasks_doctor,
        "run_command",
        lambda command, timeout_seconds, env=None: SimpleNamespace(returncode=return_code),
    )
    assert check_modal_auth(environ).status == expected_status


NODE = "laptop.example.ts.net"
LOCAL_PORTS = {"api": 8000, "llm-gateway": 3308, "mcp": 8787}


def serve_status(mappings: dict[int, int], node: str = NODE) -> dict:
    return {
        "TCP": {str(port): {"HTTPS": True} for port in mappings},
        "Web": {
            f"{node}:{port}": {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{local}"}}}
            for port, local in mappings.items()
        },
        "AllowFunnel": {f"{node}:{port}": True for port in mappings},
    }


@pytest.mark.parametrize(
    "status, expected",
    [
        (serve_status({443: 8000, 8443: 3308}), {443: 8000, 8443: 3308}),
        (serve_status({443: 8000}, node="other.example.ts.net"), {}),
        ({**serve_status({443: 8000}), "AllowFunnel": {f"{NODE}:443": False}}, {}),
        ({}, {}),
        (
            {"Foreground": {"session-a": serve_status({10000: 8787}), "session-b": serve_status({443: 8000})}},
            {10000: 8787, 443: 8000},
        ),
    ],
    ids=["funnel_listeners", "other_node", "serve_only_not_funnel", "nothing_configured", "foreground_sessions"],
)
def test_funnel_listeners(status: dict, expected: dict[int, int]) -> None:
    assert funnel_listeners(status, NODE) == expected


FUNNEL_TARGETS = [
    ("api", f"https://{NODE}/_livez"),
    ("llm-gateway", f"https://{NODE}:8443/_liveness"),
    ("mcp", f"https://{NODE}:10000/health"),
]


@pytest.mark.parametrize(
    "targets, listeners, expected",
    [
        (FUNNEL_TARGETS, {443: 8000, 8443: 3308, 10000: 8787}, []),
        (FUNNEL_TARGETS, {443: 8000, 8443: 3308}, ["mcp: no Funnel on :10000"]),
        (
            FUNNEL_TARGETS,
            {443: 8000, 8443: 9999, 10000: 8787},
            ["llm-gateway: Funnel :8443 goes to :9999, expected :3308"],
        ),
        (
            [("api", "https://someone-else.example.ts.net/_livez")],
            {},
            ["api points at someone-else.example.ts.net, not this machine"],
        ),
        ([("api", "https://api.example.ngrok.app/_livez")], {}, []),
    ],
    ids=["all_mapped", "missing_listener", "wrong_local_port", "other_machine", "non_funnel_host_ignored"],
)
def test_tunnel_problems(targets, listeners: dict[int, int], expected: list[str]) -> None:
    assert tunnel_problems(targets, NODE, listeners, LOCAL_PORTS) == expected


def test_funnel_fix_uses_foreground_commands_and_matching_urls() -> None:
    fix = funnel_fix("tailscale", NODE, LOCAL_PORTS)
    assert ("--bg" in fix, fix.splitlines()[1:4], fix.splitlines()[-1]) == (
        False,
        [
            "tailscale funnel --https=443 http://127.0.0.1:8000",
            "tailscale funnel --https=8443 http://127.0.0.1:3308",
            "tailscale funnel --https=10000 http://127.0.0.1:8787",
        ],
        f"SANDBOX_MCP_URL=https://{NODE}:10000/mcp",
    )


@pytest.mark.parametrize(
    "targets, mappings, expected_status",
    [
        ([("api", "https://api.example.ngrok.app/_livez")], {}, Status.WARN),
        (FUNNEL_TARGETS, {443: 8000, 8443: 3308, 10000: 8787}, Status.OK),
        (FUNNEL_TARGETS, {}, Status.ERROR),
    ],
    ids=["ngrok_urls", "funnel_complete", "funnel_not_started"],
)
def test_check_modal_tunnel(monkeypatch, targets, mappings: dict[int, int], expected_status: Status) -> None:
    monkeypatch.setattr(tasks_doctor, "tailscale_binary", lambda: "tailscale")
    monkeypatch.setattr(tasks_doctor, "tailscale_node", lambda binary: (NODE, None))
    monkeypatch.setattr(tasks_doctor, "tailscale_json", lambda binary, args: serve_status(mappings))
    assert check_modal_tunnel(targets, {}).status == expected_status


def test_check_modal_tunnel_without_tailscale(monkeypatch) -> None:
    monkeypatch.setattr(tasks_doctor, "tailscale_binary", lambda: None)
    assert check_modal_tunnel(FUNNEL_TARGETS, {}).status == Status.ERROR
