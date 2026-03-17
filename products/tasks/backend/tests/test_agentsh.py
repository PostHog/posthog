from django.test import TestCase, override_settings

import yaml
from parameterized import parameterized

from products.tasks.backend.services.agentsh import (
    INFRASTRUCTURE_DOMAINS,
    build_exec_prefix,
    generate_config_yaml,
    generate_policy_yaml,
)


class TestGenerateConfigYaml(TestCase):
    def test_has_ptrace_enabled(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertTrue(config["sandbox"]["ptrace"]["enabled"])
        self.assertEqual(config["sandbox"]["ptrace"]["attach_mode"], "children")

    def test_server_listens_on_localhost(self):
        config = yaml.safe_load(generate_config_yaml())
        self.assertEqual(config["server"]["http"]["addr"], "127.0.0.1:18080")

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
        self.assertIn("127.0.0.1/32", localhost_rule["cidrs"])


class TestBuildExecPrefix(TestCase):
    def test_returns_correct_format(self):
        prefix = build_exec_prefix()
        self.assertEqual(prefix, "agentsh exec $(cat /tmp/agentsh-session-id) --")


@override_settings(DEBUG=True, SANDBOX_PROVIDER="docker")
class TestAgentServerCommandWrapping(TestCase):
    def test_command_wrapped_with_agentsh_exec(self):
        from products.tasks.backend.services.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox.__new__(DockerSandbox)
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            wrap_with_agentsh=True,
        )
        self.assertIn("agentsh exec $(cat /tmp/agentsh-session-id) --", cmd)

    def test_command_not_wrapped_without_flag(self):
        from products.tasks.backend.services.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox.__new__(DockerSandbox)
        cmd = sandbox._build_agent_server_command(
            repo_path="/tmp/workspace/repos/org/repo",
            task_id="test-task",
            run_id="test-run",
            mode="background",
            wrap_with_agentsh=False,
        )
        self.assertNotIn("agentsh exec", cmd)
