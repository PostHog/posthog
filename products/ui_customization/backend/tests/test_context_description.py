from django.test import SimpleTestCase

from jsonschema import Draft202012Validator

from products.ui_customization.backend.facade import api


class TestContextDescription(SimpleTestCase):
    def test_discovery_schema_validates_defaults_and_rejects_unsupported_content(self) -> None:
        description = api.describe_customization("analytics_sidebar")
        Draft202012Validator.check_schema(description.layout_schema)
        validator = Draft202012Validator(description.layout_schema)
        layout = description.default_layout.model_dump(mode="json", exclude_none=True)
        validator.validate(layout)
        layout["sections"][0]["items"] = [{"type": "html", "html": "<b>Unsupported</b>"}]
        assert not validator.is_valid(layout)

    def test_schema_documents_cross_item_rules_and_object_labels(self) -> None:
        schema = api.describe_customization("analytics_sidebar").layout_schema
        properties = schema["properties"]
        assert isinstance(properties, dict)
        sections = properties["sections"]
        assert isinstance(sections, dict)
        assert sections["maxItems"] == 10
        rules = sections["description"]
        assert isinstance(rules, str)
        assert "30 items" in rules
        assert "4 metrics" in rules
        assert "unique" in rules
        assert "only once" in rules
        definitions = schema["$defs"]
        assert isinstance(definitions, dict)
        link = definitions["AnalyticsFragmentLink"]
        assert isinstance(link, dict)
        label_rule = link["description"]
        assert isinstance(label_rule, str)
        assert "require a label" in label_rule

    def test_unknown_context_is_not_described(self) -> None:
        with self.assertRaises(ValueError):
            api.describe_customization("unknown")
