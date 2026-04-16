from django.test import TestCase, override_settings

import yaml
from parameterized import parameterized

from products.tasks.backend.services.agentsh import (
    AGENTSH_AUDIT_DB,
    ENV_WRAPPER_SCRIPT,
    INFRASTRUCTURE_DOMAINS,
    build_audit_query_command,
    build_exec_prefix,
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
        first_deny_idx = next(i for i, rule in enumerate(rules) if rule["decision"] == "deny")
        for i, rule in enumerate(rules):
            if rule.get("decision") == "allow" and rule.get("domains"):
                self.assertLess(i, first_deny_idx)

    def test_localhost_always_allowed(self):
        policy = yaml.safe_load(generate_policy_yaml([]))
        localhost_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-localhost")
        self.assertIn("127.0.0.0/8", localhost_rule["cidrs"])

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
        allow_rule = next(rule for rule in policy["network_rules"] if rule["name"] == "allow-domains")
        self.assertIn(8000, allow_rule["ports"])
        self.assertIn(8010, allow_rule["ports"])

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


class TestEnvWrapper(TestCase):
    def test_wrapper_restores_environment_dump(self):
        wrapper = generate_env_wrapper()
        self.assertIn("done < /tmp/agent-env", wrapper)

    def test_wrapper_execs_command(self):
        wrapper = generate_env_wrapper()
        self.assertIn('exec "$@"', wrapper)

    def test_wrapper_does_not_set_proxy_vars(self):
        wrapper = generate_env_wrapper()
        self.assertNotIn("HTTPS_PROXY", wrapper)
        self.assertNotIn("NO_PROXY", wrapper)
        self.assertNotIn("--use-env-proxy", wrapper)


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


class TestBuildExecPrefix(TestCase):
    def test_returns_correct_format(self):
        self.assertEqual(
            build_exec_prefix(),
            "agentsh exec --client-timeout 2h --timeout 2h $(cat /tmp/agentsh-session-id) --",
        )


@override_settings(DEBUG=True, SANDBOX_PROVIDER="modal")
class TestModalSandboxAgentShWrapping(TestCase):
    def test_command_without_domains_skips_agentsh_exec(self):
        from products.tasks.backend.services.modal_sandbox import ModalSandbox

        sandbox = ModalSandbox.__new__(ModalSandbox)
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            create_pr=True,
        )
        self.assertNotIn("agentsh exec --client-timeout 2h --timeout 2h", cmd)
        self.assertNotIn("env -0 > /tmp/agent-env", cmd)
        self.assertNotIn(ENV_WRAPPER_SCRIPT, cmd)
        self.assertIn("nohup", cmd)

    def test_command_includes_allowed_domains(self):
        from products.tasks.backend.services.modal_sandbox import ModalSandbox

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
        self.assertIn("env -0 > /tmp/agent-env", cmd)
        self.assertIn(ENV_WRAPPER_SCRIPT, cmd)
        self.assertIn("--allowedDomains", cmd)
        self.assertIn("example.com,api.example.com", cmd)
