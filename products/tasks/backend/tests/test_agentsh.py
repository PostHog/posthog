from django.test import TestCase, override_settings

import yaml
from parameterized import parameterized

from products.tasks.backend.services.agentsh import (
    AGENTSH_AUDIT_DB,
    INFRASTRUCTURE_DOMAINS,
    build_audit_query_command,
    build_exec_prefix,
    generate_config_yaml,
    generate_env_wrapper,
    generate_policy_yaml,
)


class TestGenerateConfigYaml(TestCase):
    def test_sandbox_network_enabled(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertTrue(config["sandbox"]["network"]["enabled"])

    def test_no_ptrace_by_default(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertNotIn("ptrace", config["sandbox"])

    def test_ptrace_enabled_when_requested(self):
        config = yaml.safe_load(generate_config_yaml(enable_ptrace=True))
        self.assertTrue(config["sandbox"]["ptrace"]["enabled"])

    def test_ptrace_default_only_traces_network(self):
        config = yaml.safe_load(generate_config_yaml(enable_ptrace=True))
        trace = config["sandbox"]["ptrace"]["trace"]
        self.assertTrue(trace["network"])
        self.assertFalse(trace["execve"])
        self.assertFalse(trace["file"])
        self.assertFalse(trace["signal"])

    def test_ptrace_full_trace_enables_all(self):
        config = yaml.safe_load(generate_config_yaml(enable_ptrace=True, full_trace=True))
        trace = config["sandbox"]["ptrace"]["trace"]
        self.assertTrue(trace["network"])
        self.assertTrue(trace["execve"])
        self.assertTrue(trace["file"])
        self.assertTrue(trace["signal"])

    def test_ptrace_seccomp_prefilter_disabled(self):
        config = yaml.safe_load(generate_config_yaml(enable_ptrace=True))
        self.assertFalse(config["sandbox"]["ptrace"]["performance"]["seccomp_prefilter"])

    def test_sandbox_allows_degraded(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertTrue(config["sandbox"]["allow_degraded"])

    def test_server_listens_on_localhost(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertEqual(config["server"]["http"]["addr"], "127.0.0.1:18080")

    def test_http_timeouts_disabled(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertEqual(config["server"]["http"]["read_timeout"], "0s")
        self.assertEqual(config["server"]["http"]["write_timeout"], "0s")

    def test_session_timeouts_match_exec_timeout(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertEqual(config["sessions"]["default_timeout"], "2h")
        self.assertEqual(config["sessions"]["default_idle_timeout"], "2h")

    def test_auth_disabled(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertEqual(config["auth"]["type"], "none")

    def test_outputs_valid_yaml(self):
        raw = generate_config_yaml()
        parsed = yaml.safe_load(raw)
        self.assertIsInstance(parsed, dict)


class TestGeneratePolicyYaml(TestCase):
    def test_passes_through_provided_domains(self):
        domains = ["github.com", "custom.example.com"]
        policy = yaml.safe_load(generate_policy_yaml(domains))
        allow_rule = next(r for r in policy["network_rules"] if r["name"] == "allow-domains")
        for d in domains:
            self.assertIn(d, allow_rule["domains"])

    def test_always_includes_infrastructure_domains(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        allow_rule = next(r for r in policy["network_rules"] if r["name"] == "allow-domains")
        for d in INFRASTRUCTURE_DOMAINS:
            self.assertIn(d, allow_rule["domains"])

    def test_infrastructure_domains_not_duplicated(self):
        policy = yaml.safe_load(generate_policy_yaml(list(INFRASTRUCTURE_DOMAINS)))
        allow_rule = next(r for r in policy["network_rules"] if r["name"] == "allow-domains")
        for d in INFRASTRUCTURE_DOMAINS:
            self.assertEqual(allow_rule["domains"].count(d), 1)

    def test_outputs_valid_yaml(self):
        raw = generate_policy_yaml(["example.com"])
        parsed = yaml.safe_load(raw)
        self.assertIsInstance(parsed, dict)

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
        first_deny_idx = next(i for i, r in enumerate(rules) if r["decision"] == "deny")
        for i, rule in enumerate(rules):
            if rule.get("decision") == "allow" and rule.get("domains"):
                self.assertLess(i, first_deny_idx, f"Allow rule at index {i} after deny at {first_deny_idx}")

    def test_localhost_always_allowed(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        localhost_rule = next(r for r in policy["network_rules"] if r["name"] == "allow-localhost")
        self.assertIn("127.0.0.0/8", localhost_rule["cidrs"])

    @override_settings(DEBUG=True)
    def test_dev_ports_included_in_debug_mode(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        allow_rule = next(r for r in policy["network_rules"] if r["name"] == "allow-domains")
        self.assertIn(8000, allow_rule["ports"])
        self.assertIn(8010, allow_rule["ports"])

    @override_settings(DEBUG=False)
    def test_dev_ports_excluded_in_production(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        allow_rule = next(r for r in policy["network_rules"] if r["name"] == "allow-domains")
        self.assertNotIn(8000, allow_rule["ports"])
        self.assertNotIn(8010, allow_rule["ports"])


class TestEnvPolicy(TestCase):
    def test_env_policy_in_policy_yaml(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        self.assertIn("env_policy", policy)

    def test_env_policy_allows_posthog_vars(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        self.assertIn("POSTHOG_*", policy["env_policy"]["allow"])

    def test_env_policy_allows_proxy_vars(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        allow = policy["env_policy"]["allow"]
        self.assertIn("HTTP_PROXY", allow)
        self.assertIn("HTTPS_PROXY", allow)
        self.assertIn("NO_PROXY", allow)

    def test_env_policy_allows_system_vars(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        allow = policy["env_policy"]["allow"]
        self.assertIn("HOME", allow)
        self.assertIn("PATH", allow)

    def test_env_policy_allows_node_options(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        self.assertIn("NODE_OPTIONS", policy["env_policy"]["allow"])


class TestEnvWrapper(TestCase):
    def test_unsets_agentsh_session_vars(self):
        wrapper = generate_env_wrapper()
        self.assertIn("unset AGENTSH_IN_SESSION AGENTSH_SESSION_ID", wrapper)

    def test_sets_use_env_proxy(self):
        wrapper = generate_env_wrapper()
        self.assertIn("--use-env-proxy", wrapper)

    def test_infrastructure_domains_in_no_proxy(self):
        wrapper = generate_env_wrapper()
        self.assertIn("api.anthropic.com", wrapper)
        self.assertIn("NO_PROXY", wrapper)


class TestBuildAuditQueryCommand(TestCase):
    def test_references_audit_db(self):
        cmd = build_audit_query_command()
        self.assertIn(AGENTSH_AUDIT_DB, cmd)

    def test_queries_network_events(self):
        cmd = build_audit_query_command()
        self.assertIn("net%", cmd)

    def test_respects_limit(self):
        cmd = build_audit_query_command(limit=10)
        self.assertIn("LIMIT 10", cmd)

    def test_outputs_json(self):
        cmd = build_audit_query_command()
        self.assertIn("-json", cmd)

    def test_since_ns_adds_timestamp_filter(self):
        cmd = build_audit_query_command(since_ns=1000)
        self.assertIn("ts_unix_ns > 1000", cmd)

    def test_since_ns_zero_omits_timestamp_filter(self):
        cmd = build_audit_query_command(since_ns=0)
        self.assertNotIn("ts_unix_ns >", cmd)

    def test_since_ns_combined_with_limit(self):
        cmd = build_audit_query_command(since_ns=5000, limit=25)
        self.assertIn("ts_unix_ns > 5000", cmd)
        self.assertIn("LIMIT 25", cmd)


class TestBuildExecPrefix(TestCase):
    def test_returns_correct_format(self):
        prefix = build_exec_prefix()
        self.assertEqual(prefix, "agentsh exec --client-timeout 2h --timeout 2h $(cat /tmp/agentsh-session-id) --")

    def test_includes_client_timeout(self):
        prefix = build_exec_prefix()
        self.assertIn("--client-timeout 2h", prefix)

    def test_includes_command_timeout(self):
        prefix = build_exec_prefix()
        self.assertIn("--timeout 2h", prefix)


@override_settings(DEBUG=True, SANDBOX_PROVIDER="docker")
class TestAgentServerCommandWrapping(TestCase):
    def _make_sandbox(self):
        from products.tasks.backend.services.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox.__new__(DockerSandbox)
        return sandbox

    def test_command_uses_agentsh_exec_with_wrapping(self):
        sandbox = self._make_sandbox()
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            wrap_with_agentsh=True,
        )
        self.assertIn("agentsh exec", cmd)
        self.assertIn("env -0 >", cmd)
        self.assertIn("/tmp/agentsh-env-wrapper.sh", cmd)
        self.assertNotIn("HTTP_PROXY", cmd)

    def test_command_uses_nohup_with_agentsh(self):
        sandbox = self._make_sandbox()
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            wrap_with_agentsh=True,
        )
        self.assertIn("nohup", cmd)

    def test_command_uses_absolute_path_with_agentsh(self):
        sandbox = self._make_sandbox()
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            wrap_with_agentsh=True,
        )
        self.assertIn("/scripts/node_modules/.bin/agent-server", cmd)

    def test_command_uses_nohup_without_agentsh(self):
        sandbox = self._make_sandbox()
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            wrap_with_agentsh=False,
        )
        self.assertIn("nohup", cmd)
        self.assertNotIn("agentsh exec", cmd)
