import pytest

from products.enterprise.backend.hogai.utils.yaml import YamlOutputParser


class TestYamlOutputParser:
    @pytest.mark.parametrize(
        "input_text,expected_output",
        [
            # Simple YAML dict
            ("key: value", {"key": "value"}),
            # YAML with markdown code block
            ("```yaml\nkey: value\n```", {"key": "value"}),
            # YAML list
            ("- item1\n- item2", ["item1", "item2"]),
            # YAML with markdown and list
            ("```yaml\n- item1\n- item2\n```", ["item1", "item2"]),
            # Nested YAML dict
            ("parent:\n  child: value", {"parent": {"child": "value"}}),
            # YAML with markdown and nested structure
            ("```yaml\nparent:\n  child: value\n```", {"parent": {"child": "value"}}),
            # YAML with extra whitespace
            ("  key: value  ", {"key": "value"}),
            # Empty YAML dict
            ("{}", {}),
            # Empty YAML list
            ("[]", []),
        ],
    )
    def test_parse(self, input_text, expected_output):
        parser = YamlOutputParser()
        assert parser.parse(input_text) == expected_output
