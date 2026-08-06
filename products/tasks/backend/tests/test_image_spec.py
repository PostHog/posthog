import pytest

from parameterized import parameterized

from products.tasks.backend.logic.services.image_spec import (
    MAX_RUN_COMMANDS,
    SandboxImageSpecError,
    parse_image_spec_yaml,
    spec_json_to_yaml,
)


class TestParseImageSpecYaml:
    def test_parses_full_spec_and_roundtrips_yaml(self):
        spec = parse_image_spec_yaml(
            "version: 1\napt_packages: [postgresql-client]\nrun_commands: ['curl -fsSL https://flox.dev | bash']\nenv:\n  TOOL_HOME: /opt/tool\n"
        )
        assert spec.apt_packages == ["postgresql-client"]
        assert spec.env == {"TOOL_HOME": "/opt/tool"}
        assert not spec.is_empty
        assert parse_image_spec_yaml(spec.to_yaml()) == spec

    def test_version_is_optional_and_hidden_from_display_yaml(self):
        spec = parse_image_spec_yaml("apt_packages: [jq]\n")
        assert spec.version == 1
        display = spec_json_to_yaml(spec.model_dump())
        assert "version" not in display
        assert parse_image_spec_yaml(display) == spec

    def test_repo_setup_commands_parse_and_count_as_content(self):
        spec = parse_image_spec_yaml("repo_setup_commands: ['pnpm install --frozen-lockfile']\n")
        assert spec.repo_setup_commands == ["pnpm install --frozen-lockfile"]
        assert not spec.is_empty

    def test_joins_backslash_continuations_into_single_line(self):
        spec = parse_image_spec_yaml(
            "run_commands:\n  - |-\n    curl -fsSL https://example.com/tool.tar.gz \\\n      -o /tmp/tool.tar.gz\n"
        )
        assert spec.run_commands == ["curl -fsSL https://example.com/tool.tar.gz -o /tmp/tool.tar.gz"]

    @parameterized.expand(
        [
            ("not_yaml", "version: [unclosed"),
            ("not_mapping", "- a\n- b\n"),
            ("wrong_version", "version: 2\napt_packages: [jq]\n"),
            ("shell_metachars_in_apt", "version: 1\napt_packages: ['jq && curl evil.sh']\n"),
            ("uppercase_apt", "version: 1\napt_packages: [Postgres]\n"),
            ("empty_command", "version: 1\nrun_commands: ['  ']\n"),
            (
                "raw_newline_in_command",
                "run_commands:\n  - |-\n    mkdir -p /opt/x\n    curl -o /tmp/f https://example.com\n",
            ),
            ("empty_repo_setup_command", "repo_setup_commands: ['  ']\n"),
            ("blocked_env_prefix", "version: 1\nenv:\n  GIT_SSH_COMMAND: evil\n"),
            ("blocked_env_key", "version: 1\nenv:\n  NODE_OPTIONS: --require /tmp/x\n"),
            ("reserved_env_key", "version: 1\nenv:\n  GITHUB_TOKEN: ghs_stolen\n"),
            ("invalid_env_key", "version: 1\nenv:\n  9BAD: x\n"),
            ("too_many_commands", "version: 1\nrun_commands: [" + ", ".join(["ls"] * (MAX_RUN_COMMANDS + 1)) + "]\n"),
        ]
    )
    def test_rejects_invalid_specs(self, _name, raw):
        with pytest.raises(SandboxImageSpecError):
            parse_image_spec_yaml(raw)

    @parameterized.expand(
        [
            (
                "command_with_unquoted_colon",
                'run_commands:\n  - ls\n  - curl -H "Accept: application/json" https://example.com\n',
                "run_commands entry 2 was read as a YAML mapping, not a command, because the line contains ': ' and YAML splits that into a key and a value. Wrap the whole command in single quotes, or write it as a '|-' block: curl -H \"Accept: application/json\" https://example.com",
            ),
            (
                "apt_package_with_unquoted_colon",
                "apt_packages:\n  - postgresql-client: needed\n",
                "apt_packages entry 1 was read as a YAML mapping, not a package name",
            ),
            (
                "unquoted_numeric_env_value",
                "env:\n  PORT: 8080\n",
                "Env var PORT has a non-text value: 8080. Wrap it in quotes so YAML keeps it as text",
            ),
        ]
    )
    def test_explains_yaml_type_surprises(self, _name, raw, expected_message):
        with pytest.raises(SandboxImageSpecError) as excinfo:
            parse_image_spec_yaml(raw)
        message = str(excinfo.value)
        assert expected_message in message
        assert "pydantic" not in message
