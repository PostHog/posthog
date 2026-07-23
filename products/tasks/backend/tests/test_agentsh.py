import os
import shlex
import tempfile
import subprocess
from pathlib import Path
from typing import Any

from unittest.mock import Mock

from django.test import SimpleTestCase, TestCase, override_settings

import yaml
from parameterized import parameterized

from products.tasks.backend.logic.services.agentsh import (
    AGENTSH_AUDIT_DB,
    ENV_WRAPPER_SCRIPT,
    INFRASTRUCTURE_DOMAINS,
    build_audit_query_command,
    build_exec_prefix,
    generate_bash_env_script,
    generate_config_yaml,
    generate_env_wrapper,
    generate_policy_yaml,
)


class TestGenerateConfigYaml(TestCase):
    def test_has_ptrace_enabled_with_full_trace(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertTrue(config["sandbox"]["ptrace"]["enabled"])
        self.assertEqual(config["sandbox"]["ptrace"]["attach_mode"], "children")
        self.assertTrue(config["sandbox"]["ptrace"]["trace"]["file"])
        self.assertTrue(config["sandbox"]["ptrace"]["trace"]["execve"])
        self.assertTrue(config["sandbox"]["ptrace"]["trace"]["signal"])

    def test_server_listens_on_localhost(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertEqual(config["server"]["http"]["addr"], "127.0.0.1:18080")

    def test_disables_http_timeouts(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertEqual(config["server"]["http"]["read_timeout"], "0s")
        self.assertEqual(config["server"]["http"]["write_timeout"], "0s")

    def test_uses_real_paths(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertTrue(config["sessions"]["real_paths"])

    def test_long_session_timeouts(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertEqual(config["sessions"]["default_timeout"], "2h")
        self.assertEqual(config["sessions"]["default_idle_timeout"], "2h")

    def test_outputs_valid_yaml(self):
        raw = generate_config_yaml()
        parsed = yaml.safe_load(raw)
        self.assertIsInstance(parsed, dict)


class TestGeneratePolicyYaml(TestCase):
    def test_allows_commands(self):
        policy = yaml.safe_load(generate_policy_yaml(["example.com"]))
        allow_rule = next(rule for rule in policy["command_rules"] if rule["name"] == "allow-all-commands")
        self.assertEqual(allow_rule["commands"], ["*"])
        self.assertEqual(allow_rule["decision"], "allow")

    def test_passes_through_provided_domains(self):
        domains = ["github.com", "custom.example.com"]
        policy = yaml.safe_load(generate_policy_yaml(domains))
        allow_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-domains")
        for domain in domains:
            self.assertIn(domain, allow_rule["domains"])

    def test_always_includes_infrastructure_domains(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        allow_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-domains")
        for domain in INFRASTRUCTURE_DOMAINS:
            self.assertIn(domain, allow_rule["domains"])

    def test_always_includes_gateway_domains(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        allow_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-domains")
        self.assertIn("gateway.us.posthog.com", allow_rule["domains"])
        self.assertIn("gateway.eu.posthog.com", allow_rule["domains"])

    def test_default_deny_at_end(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        last_rule = policy["network_rules"][-1]
        self.assertEqual(last_rule["decision"], "deny")

    @parameterized.expand(
        [
            ([],),
            (["api.example.com"],),
            (["a.com", "b.com", "c.com"],),
        ]
    )
    def test_allowed_domains_before_deny_rules(self, domains):
        policy = yaml.safe_load(generate_policy_yaml(domains))
        rules = policy["network_rules"]
        default_deny_idx = next(i for i, rule in enumerate(rules) if rule["name"] == "default-deny-network")
        for i, rule in enumerate(rules):
            if rule.get("decision") == "allow" and rule.get("domains"):
                self.assertLess(i, default_deny_idx)

    def test_localhost_always_allowed(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        localhost_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-localhost")
        self.assertIn("127.0.0.0/8", localhost_rule["cidrs"])

    def test_restricted_policy_denies_cloud_metadata(self):
        policy = yaml.safe_load(generate_policy_yaml(["example.com"]))
        metadata_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "deny-cloud-metadata")
        self.assertEqual(metadata_rule["decision"], "deny")
        self.assertIn("169.254.169.254/32", metadata_rule["cidrs"])
        self.assertIn("fd00:ec2::254/128", metadata_rule["cidrs"])

    def test_cloud_metadata_deny_precedes_allowed_domains(self):
        policy = yaml.safe_load(generate_policy_yaml(["example.com"]))
        rules = policy["network_rules"]
        metadata_idx = next(i for i, rule in enumerate(rules) if rule["name"] == "deny-cloud-metadata")
        allow_domains_idx = next(i for i, rule in enumerate(rules) if rule["name"] == "allow-domains")
        self.assertLess(metadata_idx, allow_domains_idx)

    def test_file_rules_allow_all(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        file_rule = next(rule for rule in policy["file_rules"] if rule["name"] == "allow-all-files")
        self.assertEqual(file_rule["paths"], ["**"])

    def test_env_policy_allows_posthog_vars(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        self.assertIn("POSTHOG_*", policy["env_policy"]["allow"])

    @override_settings(DEBUG=True)
    def test_debug_mode_adds_dev_ports(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        debug_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-debug-domains")
        self.assertIn(8000, debug_rule["ports"])
        self.assertIn(8010, debug_rule["ports"])

    @override_settings(DEBUG=True)
    def test_debug_mode_keeps_prod_rule_restricted_to_cloud_ports(self):
        # DEBUG additions land in `allow-debug-domains`, not `allow-domains` —
        # the prod rule stays identical across environments so a debug-only
        # port can't accidentally widen prod.
        policy = yaml.safe_load(generate_policy_yaml([]))
        allow_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-domains")
        self.assertEqual(sorted(allow_rule["ports"]), [22, 80, 443])

    @override_settings(
        DEBUG=True,
        SANDBOX_LLM_GATEWAY_URL="http://host.docker.internal:3308",
        SANDBOX_MCP_URL="http://host.docker.internal:8787/mcp",
    )
    def test_debug_mode_adds_ports_from_sandbox_url_settings(self):
        # Local llm-gateway (3308) and MCP wrangler (8787) listen on non-standard
        # ports — without including them in `allow-debug-domains.ports`, agentsh
        # denies the connect at the syscall layer even when the hostname is allowed.
        policy = yaml.safe_load(generate_policy_yaml([]))
        debug_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-debug-domains")
        self.assertIn(3308, debug_rule["ports"])
        self.assertIn(8787, debug_rule["ports"])

    @override_settings(
        DEBUG=True,
        SANDBOX_LLM_GATEWAY_URL="http://host.docker.internal:3308",
    )
    def test_debug_mode_adds_sandbox_hosts_to_debug_rule(self):
        # Parsed sandbox hostnames belong on the DEBUG rule, not the prod rule.
        policy = yaml.safe_load(generate_policy_yaml([]))
        debug_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-debug-domains")
        allow_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-domains")
        self.assertIn("host.docker.internal", debug_rule["domains"])
        self.assertNotIn("host.docker.internal", allow_rule["domains"])

    @override_settings(DEBUG=False, SANDBOX_LLM_GATEWAY_URL="http://example.local:3308")
    def test_non_debug_mode_omits_debug_rule_entirely(self):
        # Outside DEBUG the debug rule should not exist, and the prod rule
        # must not absorb any sandbox URL hostnames or non-cloud ports.
        policy = yaml.safe_load(generate_policy_yaml([]))
        rule_names = [rule["name"] for rule in policy["network_rules"]]
        self.assertNotIn("allow-debug-domains", rule_names)
        allow_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-domains")
        self.assertEqual(sorted(allow_rule["ports"]), [22, 80, 443])
        self.assertNotIn("example.local", allow_rule["domains"])

    @override_settings(
        DEBUG=True,
        # Non-numeric port — `urlparse(...).port` raises ValueError on access.
        SANDBOX_API_URL="http://host:abc",
        # Out-of-range port (>65535) — also raises ValueError.
        SANDBOX_LLM_GATEWAY_URL="http://host:99999",
    )
    def test_debug_mode_tolerates_malformed_sandbox_urls(self):
        # A typo in `SANDBOX_*_URL` should not crash `generate_policy_yaml`.
        # Malformed ports degrade silently to "no port added"; the base DEBUG
        # ports (8000/8010) and prod ports (22/80/443) are preserved so the
        # sandbox still boots with a sane allowlist.
        policy = yaml.safe_load(generate_policy_yaml([]))
        debug_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-debug-domains")
        allow_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-domains")
        for port in (8000, 8010):
            self.assertIn(port, debug_rule["ports"])
        self.assertEqual(sorted(allow_rule["ports"]), [22, 80, 443])

    @override_settings(DEBUG=True, SANDBOX_LLM_GATEWAY_URL="not-a-url-at-all://")
    def test_debug_mode_tolerates_malformed_sandbox_hostname(self):
        # Companion to the port-side guard — `_hostname_from_url` should
        # degrade silently rather than crash policy generation.
        policy = yaml.safe_load(generate_policy_yaml([]))
        debug_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-debug-domains")
        # Localhost + host.docker.internal are still present.
        self.assertIn("localhost", debug_rule["domains"])
        self.assertIn("host.docker.internal", debug_rule["domains"])

    def test_allow_all_policy_when_no_domains(self):
        policy = yaml.safe_load(generate_policy_yaml(None))
        rules = policy["network_rules"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["name"], "allow-all-network")
        self.assertEqual(rules[0]["decision"], "allow")

    def test_allow_all_policy_has_no_deny_rules(self):
        policy = yaml.safe_load(generate_policy_yaml(None))
        deny_rules = [r for r in policy["network_rules"] if r["decision"] == "deny"]
        self.assertEqual(len(deny_rules), 0)

    def test_allow_all_policy_has_no_metadata_deny_rule(self):
        policy = yaml.safe_load(generate_policy_yaml(None))
        rule_names = [r["name"] for r in policy["network_rules"]]
        self.assertNotIn("deny-cloud-metadata", rule_names)


class TestEnvWrapper(SimpleTestCase):
    def test_restores_safe_environment_and_only_managed_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "agent env"
            github_env_file = Path(temp_dir) / "github env"
            oauth_env_file = Path(temp_dir) / "oauth env"
            wrapper_file = Path(temp_dir) / "wrapper.sh"
            env_file.write_bytes(
                b"SAFE_BASE=kept\x00NODE_OPTIONS=--require=/tmp/payload.js\x00GITHUB_TOKEN=ghs_snapshot\x00"
            )
            github_env_file.write_bytes(b"GITHUB_TOKEN=ghs_fresh\x00GH_TOKEN=ghs_fresh\x00IGNORED=unsafe\x00")
            oauth_env_file.write_bytes(b"POSTHOG_PERSONAL_API_KEY=oauth_fresh\x00IGNORED=unsafe\x00")
            wrapper_file.write_text(generate_env_wrapper(str(env_file), str(github_env_file), str(oauth_env_file)))

            result = subprocess.run(
                [
                    "bash",
                    str(wrapper_file),
                    "bash",
                    "-c",
                    'printf "%s|%s|%s|%s|%s" "$SAFE_BASE" "$GH_TOKEN" "$GITHUB_TOKEN" '
                    '"$POSTHOG_PERSONAL_API_KEY" "${NODE_OPTIONS:-}"',
                ],
                check=True,
                capture_output=True,
                text=True,
                env={"PATH": os.environ["PATH"], "NODE_OPTIONS": "--require=/tmp/inherited.js"},
            )

            self.assertEqual(result.stdout, "kept|ghs_fresh|ghs_fresh|oauth_fresh|")

    def test_wrapper_does_not_set_proxy_vars(self):
        wrapper = generate_env_wrapper()
        self.assertNotIn("HTTPS_PROXY", wrapper)
        self.assertNotIn("NO_PROXY", wrapper)
        self.assertNotIn("--use-env-proxy", wrapper)


class TestBashEnvScript(SimpleTestCase):
    def test_initialization_replaces_snapshot_env_and_preserves_refreshed_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "agent env"
            github_env_file = Path(temp_dir) / "github env"
            oauth_env_file = Path(temp_dir) / "oauth env"
            script_file = Path(temp_dir) / "bash env.sh"
            env_file.write_bytes(
                b"PATH=/snapshot\x00NODE_OPTIONS=--require=/tmp/payload.js\x00GITHUB_TOKEN=ghu_snapshot\x00"
            )
            github_env_file.write_bytes(b"GH_TOKEN=ghu_fresh\x00GITHUB_TOKEN=ghu_fresh\x00")
            oauth_env_file.write_bytes(b"POSTHOG_PERSONAL_API_KEY=oauth_fresh\x00")
            script_file.write_text(generate_bash_env_script(str(env_file), str(github_env_file), str(oauth_env_file)))

            subprocess.run(
                ["bash", str(script_file)],
                check=True,
                env={
                    "PATH": os.environ["PATH"],
                    "SAFE_BASE": "kept",
                    "GH_TOKEN": "ghu_process",
                    "POSTHOG_PERSONAL_API_KEY": "oauth_process",
                    "NODE_OPTIONS": "--require=/tmp/current.js",
                },
            )

            entries = {
                entry.split(b"=", 1)[0]: entry.split(b"=", 1)[1]
                for entry in env_file.read_bytes().split(b"\x00")
                if entry
            }
            self.assertEqual(entries[b"SAFE_BASE"], b"kept")
            self.assertNotIn(b"NODE_OPTIONS", entries)
            self.assertNotIn(b"GITHUB_TOKEN", entries)
            self.assertNotIn(b"POSTHOG_PERSONAL_API_KEY", entries)
            self.assertEqual(github_env_file.read_bytes(), b"GH_TOKEN=ghu_fresh\x00GITHUB_TOKEN=ghu_fresh\x00")
            self.assertEqual(oauth_env_file.read_bytes(), b"POSTHOG_PERSONAL_API_KEY=oauth_fresh\x00")
            for path in (env_file, github_env_file, oauth_env_file):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

            sourced = subprocess.run(
                ["bash", "-c", 'printf "%s|%s" "$GH_TOKEN" "$GITHUB_TOKEN"'],
                check=True,
                capture_output=True,
                text=True,
                env={"PATH": os.environ["PATH"], "BASH_ENV": str(script_file)},
            )
            self.assertEqual(sourced.stdout, "ghu_fresh|ghu_fresh")

    def test_initialization_creates_restrictive_credential_files_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "agent env"
            github_env_file = Path(temp_dir) / "github env"
            oauth_env_file = Path(temp_dir) / "oauth env"
            script_file = Path(temp_dir) / "bash env.sh"
            script_file.write_text(generate_bash_env_script(str(env_file), str(github_env_file), str(oauth_env_file)))

            subprocess.run(
                ["bash", str(script_file)],
                check=True,
                env={
                    "PATH": os.environ["PATH"],
                    "SAFE_BASE": "kept",
                    "GITHUB_TOKEN": "ghs_current",
                    "POSTHOG_PERSONAL_API_KEY": "oauth_current",
                },
            )

            self.assertEqual(
                github_env_file.read_bytes(),
                b"GITHUB_TOKEN=ghs_current\x00GH_TOKEN=ghs_current\x00",
            )
            self.assertEqual(oauth_env_file.read_bytes(), b"POSTHOG_PERSONAL_API_KEY=oauth_current\x00")
            for path in (env_file, github_env_file, oauth_env_file):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_initialization_fails_for_untrusted_credential_file_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "agent env"
            github_env_file = Path(temp_dir) / "github env"
            oauth_env_file = Path(temp_dir) / "oauth env"
            script_file = Path(temp_dir) / "bash env.sh"
            github_env_file.mkdir()
            script_file.write_text(generate_bash_env_script(str(env_file), str(github_env_file), str(oauth_env_file)))

            result = subprocess.run(
                ["bash", str(script_file)],
                check=False,
                env={"PATH": os.environ["PATH"]},
            )

            self.assertNotEqual(result.returncode, 0)


class TestBuildAuditQueryCommand(TestCase):
    def test_references_audit_db(self):
        cmd = build_audit_query_command()
        self.assertIn(AGENTSH_AUDIT_DB, cmd)

    def test_filters_network_events(self):
        cmd = build_audit_query_command()
        self.assertIn("net%", cmd)

    def test_respects_limit(self):
        cmd = build_audit_query_command(limit=10)
        self.assertIn("LIMIT 10", cmd)

    def test_command_is_shell_parseable(self):
        cmd = build_audit_query_command(limit=10)
        parts = shlex.split(cmd)
        self.assertEqual(parts[0], "sqlite3")
        self.assertTrue(any(part.startswith("SELECT ts_unix_ns") for part in parts))


class TestBuildExecPrefix(TestCase):
    def test_returns_correct_format(self):
        self.assertEqual(
            build_exec_prefix(),
            "agentsh exec --client-timeout 2h --timeout 2h $(cat /tmp/agentsh-session-id) --",
        )


@override_settings(DEBUG=True, SANDBOX_PROVIDER="modal")
class TestModalSandboxAgentShWrapping(TestCase):
    def test_command_without_domains_skips_agentsh_exec(self):
        from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox

        sandbox = ModalSandbox.__new__(ModalSandbox)
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            create_pr=True,
        )
        self.assertNotIn("agentsh exec --client-timeout 2h --timeout 2h", cmd)
        self.assertIn("bash /tmp/agentsh-bash-env.sh", cmd)
        self.assertNotIn(ENV_WRAPPER_SCRIPT, cmd)
        self.assertIn("nohup", cmd)

    @parameterized.expand(
        [
            ("modal", True),
            ("modal", False),
            ("docker", True),
            ("docker", False),
        ]
    )
    def test_command_includes_auto_publish_flag_only_when_opted_in(self, provider, auto_publish):
        from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
        from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox

        sandbox: ModalSandbox | DockerSandbox
        if provider == "modal":
            sandbox = ModalSandbox.__new__(ModalSandbox)
        else:
            sandbox = DockerSandbox.__new__(DockerSandbox)
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            create_pr=True,
            auto_publish=auto_publish,
        )
        # Opt-out runs must not see the flag at all: agent-server builds without
        # the option reject unknown flags, so appending it would break every run.
        if auto_publish:
            self.assertIn("--autoPublish true", cmd)
        else:
            self.assertNotIn("--autoPublish", cmd)

    @parameterized.expand(
        [
            ("modal", True),
            ("modal", False),
            ("docker", True),
            ("docker", False),
        ]
    )
    def test_start_agent_server_drops_auto_publish_when_binary_lacks_support(self, provider, supported):
        from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
        from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
        from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxConfig

        # Snapshots restored from old images carry an agent-server that rejects unknown
        # options; the launch probe must drop --autoPublish instead of crashing the run.
        launched: list[str] = []

        def execute(command: str, timeout_seconds: int | None = None) -> ExecutionResult:
            if "--taskId" in command:
                launched.append(command)
                return ExecutionResult(stdout="", stderr="", exit_code=0)
            if "chmod" in command:  # gh shim install
                return ExecutionResult(stdout="", stderr="", exit_code=0)
            self.assertIn("grep", command)
            return ExecutionResult(stdout="", stderr="", exit_code=0 if supported else 1)

        sandbox: ModalSandbox | DockerSandbox
        if provider == "modal":
            sandbox = ModalSandbox.__new__(ModalSandbox)
        else:
            sandbox = DockerSandbox.__new__(DockerSandbox)
            sandbox._host_port = 8080
        sandbox.id = "sb-test"
        sandbox.config = SandboxConfig(name="sb-test")
        cast_sandbox: Any = sandbox
        cast_sandbox.is_running = Mock(return_value=True)
        cast_sandbox._agent_server_is_healthy = Mock(return_value=False)
        cast_sandbox._free_agent_server_port = Mock()
        cast_sandbox.write_file = Mock()
        cast_sandbox.execute = execute

        sandbox.start_agent_server(
            repository="org/repo",
            task_id="test-task",
            run_id="test-run",
            auto_publish=True,
            wait_for_health=False,
        )

        self.assertEqual(len(launched), 1)
        if supported:
            self.assertIn("--autoPublish true", launched[0])
        else:
            self.assertNotIn("--autoPublish", launched[0])

    def test_command_includes_allowed_domains(self):
        from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox

        sandbox = ModalSandbox.__new__(ModalSandbox)
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            create_pr=True,
            allowed_domains=["example.com", "api.example.com"],
        )
        self.assertIn("agentsh exec --client-timeout 2h --timeout 2h", cmd)
        self.assertIn("bash /tmp/agentsh-bash-env.sh", cmd)
        self.assertIn(ENV_WRAPPER_SCRIPT, cmd)
        self.assertIn("--allowedDomains", cmd)
        self.assertIn("example.com,api.example.com", cmd)

    def test_command_includes_runtime_environment_variables(self):
        from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox

        sandbox = ModalSandbox.__new__(ModalSandbox)
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            create_pr=True,
            runtime_adapter="codex",
            provider="openai",
            model="gpt-5.3-codex",
            reasoning_effort="high",
        )
        self.assertIn("POSTHOG_CODE_RUNTIME_ADAPTER=codex", cmd)
        self.assertIn("POSTHOG_CODE_PROVIDER=openai", cmd)
        self.assertIn("POSTHOG_CODE_MODEL=gpt-5.3-codex", cmd)
        self.assertIn("POSTHOG_CODE_REASONING_EFFORT=high", cmd)

    def test_write_file_uses_filesystem_api_before_rename(self):
        from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
        from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxConfig

        sandbox = ModalSandbox.__new__(ModalSandbox)
        sandbox.id = "sb-123"
        sandbox.config = SandboxConfig(name="test-sandbox")
        sandbox_any = sandbox  # Help mypy treat test doubles as dynamic attributes.
        cast_sandbox: Any = sandbox_any
        cast_sandbox.is_running = Mock(return_value=True)
        cast_sandbox.execute = Mock(return_value=ExecutionResult(stdout="", stderr="", exit_code=0, error=None))
        cast_sandbox._sandbox = Mock()
        cast_sandbox._sandbox.filesystem = Mock()

        result = sandbox.write_file("/tmp/workspace/config.yaml", b"payload")

        cast_sandbox._sandbox.filesystem.write_bytes.assert_called_once()
        write_payload, write_path = cast_sandbox._sandbox.filesystem.write_bytes.call_args.args
        self.assertTrue(write_path.startswith("/tmp/workspace/config.yaml.tmp-"))
        self.assertEqual(write_payload, b"payload")
        cast_sandbox.execute.assert_called_once()
        self.assertIn("mv", cast_sandbox.execute.call_args.args[0])
        self.assertEqual(result.exit_code, 0)
