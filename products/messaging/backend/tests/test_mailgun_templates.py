import json
from pathlib import Path

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports import mailgun_templates
from products.messaging.backend.provider_imports.mailgun_templates import convert_text, convert_version

ESCAPED_X = '{{ variables.x | join: "," | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}'
RENDER_CASES = json.loads((Path(__file__).parent / "fixtures" / "mailgun_template_renders.json").read_text())


class TestMailgunTemplateConversion(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in RENDER_CASES])
    def test_converted_templates_match_the_rendered_fixture(self, _name: str, case: dict) -> None:
        assert convert_text(case["template"], engine=case["engine"]).text == case["liquid"]

    @parameterized.expand(
        [
            ("text", "handlebars", "<p>{{x}}</p>", f"<p>{ESCAPED_X}</p>"),
            ("spaces", "handlebars", "<p>{{ x }}</p>", f"<p>{ESCAPED_X}</p>"),
            ("raw_in_text", "handlebars", "<p>{{{x}}}</p>", "<p>{{ variables.x | raw }}</p>"),
            ("handlebars_link", "handlebars", '<a href="{{x}}">', f'<a href="{ESCAPED_X}">'),
            (
                "after_a_style",
                "handlebars",
                "<style>p{}</style><p>{{x}}</p>",
                f"<style>p{{}}</style><p>{ESCAPED_X}</p>",
            ),
            ("after_a_stray_less_than", "handlebars", "a<3 {{x}}", f"a<3 {ESCAPED_X}"),
            ("brace_before_a_value", "handlebars", "{ {{x}}", f"{{ {ESCAPED_X}"),
            ("liquid_in_text", "handlebars", "{% if a %}{{x}}", '{{ "{%" }} if a %}' + ESCAPED_X),
        ]
    )
    def test_a_plain_value_converts(self, _name: str, engine: str, source: str, expected: str) -> None:
        converted = convert_text(source, engine=engine)  # type: ignore[arg-type]

        assert converted.text == expected
        assert not converted.unsupported

    @parameterized.expand(
        [
            ("condition", "handlebars", "{{#if a}}x{{/if}}"),
            ("loop", "go", "{{range .Items}}x{{end}}"),
            ("helper", "handlebars", "{{lookup a b}}"),
            ("comment", "handlebars", "{{! note }}<p>{{x}}</p>"),
            ("go_comment_with_a_tab", "go", "{{-\t/* c */ -}}<img src=x onerror=alert(1)>"),
            ("go_trim", "go", "{{- .x -}}"),
            ("handlebars_escape", "handlebars", "\\{{x}}"),
            ("backslash_before_a_go_tag", "go", '\\{{printf "<img src=x onerror=alert(1)>"}}'),
            ("parent_path", "handlebars", "{{../x}}"),
            ("unclosed", "handlebars", "a {{ b"),
            ("unquoted_attribute", "handlebars", "<a href={{x}}>"),
            ("attribute_name", "handlebars", '<a {{x}}="y">'),
            ("event_handler", "handlebars", '<a onclick="{{x}}">'),
            ("style_attribute", "handlebars", '<p style="color: {{x}}">'),
            ("raw_in_an_attribute", "handlebars", '<a title="{{{x}}}">'),
            ("go_link", "go", '<a href="{{.x}}">'),
            ("go_data_attribute", "go", '<a data-href="{{.x}}">'),
            ("go_meta_refresh", "go", '<meta http-equiv="refresh" content="0;url={{.x}}">'),
            ("go_plain_attribute", "go", '<a title="{{.x}}">'),
            (
                "after_a_script_that_hides_its_end",
                "handlebars",
                "<script><!--<script></script>--></script><p>{{x}}</p>",
            ),
            ("after_any_script", "handlebars", "<script>x</script><p>{{x}}</p>"),
            ("script", "handlebars", "<script>var x = {{x}};</script>"),
            ("style", "handlebars", "<style>p { color: {{x}} }</style>"),
            ("html_comment", "handlebars", "<!-- {{x}} -->"),
            ("recipient_variable_in_a_script", "handlebars", "<script>%recipient.x%</script>"),
        ]
    )
    def test_anything_else_keeps_the_whole_template_as_text(self, _name: str, engine: str, source: str) -> None:
        converted = convert_text(source, engine=engine)  # type: ignore[arg-type]

        assert converted.unsupported
        assert "variables." not in converted.text
        assert "<img" not in converted.text and "<script" not in converted.text
        assert "{{" not in converted.text.replace('{{ "{{" }}', "").replace('{{ "{%" }}', "")

    def test_a_template_kept_as_text_has_a_note(self) -> None:
        converted = convert_version({"template": "{{#if a}}x{{/if}}", "headers": {"Subject": "Hi"}})

        assert any("only converts plain values" in note and "{{#if a}}" in note for note in converted.notes)

    @parameterized.expand(
        [
            ("fixed", "%recipient_email%", True, ESCAPED_X.replace("variables.x", "variables.recipient_email")),
            ("custom", "%recipient.first-name%", True, ESCAPED_X.replace("variables.x", "variables.first-name")),
            ("custom_text", "%recipient.city%", False, '{{ variables.city | join: "," }}'),
            ("custom_with_space_stays", "%recipient.a b%", True, "%recipient.a b%"),
            ("unsubscribe_in_a_link", 'href="%unsubscribe_url%"', True, 'href="{{ unsubscribe_url }}"'),
            ("percent_signs_alone", "100% of 50%", True, "100% of 50%"),
            ("unsubscribe_email_stays", "%unsubscribe_email%", True, "%unsubscribe_email%"),
            ("triple_in_subject_has_no_raw", "{{{x}}}", False, '{{ variables.x | join: "," }}'),
        ]
    )
    def test_mailgun_variables(self, _name: str, source: str, is_html: bool, expected: str) -> None:
        assert convert_text(source, is_html=is_html).text == expected

    @parameterized.expand(
        [
            ("no_subject", {"template": "x"}, "no subject"),
            ("variable_subject", {"template": "x", "headers": {"Subject": "{{a}}"}}, "subject uses variables"),
            ("tag_unsubscribe", {"template": "%tag_unsubscribe_url%"}, "message category"),
            ("list_unsubscribe", {"template": "%mailing_list_unsubscribe_url%"}, "imported from the list"),
            ("unknown_engine", {"template": "x", "engine": "mustache"}, "lists the engine mustache"),
            ("go", {"template": "{{.x}}", "engine": "go"}, "Go templates"),
        ]
    )
    def test_notes_name_what_to_review(self, _name: str, version: dict, expected: str) -> None:
        assert any(expected in note for note in convert_version(version).notes)

    def test_a_go_value_prints_lists_and_maps_the_go_way(self) -> None:
        converted = convert_text("<p>{{.x}}</p>", engine="go").text

        assert '{% if go_value1 == "[" %}[' in converted
        assert "map[{% for pair in variables.x %}" in converted

    def test_a_blank_engine_with_go_syntax_reads_as_go(self) -> None:
        assert "variables.Name" in convert_version({"engine": "", "template": "{{.Name}}"}).html

    def test_many_values_scan_in_linear_time(self) -> None:
        converted = convert_text("<p>{{x}}</p>" * 30_000)

        assert converted.text.count("variables.x") == 30_000

    def test_a_huge_template_is_cut_before_its_fallback_text_is_built(self) -> None:
        with patch.object(mailgun_templates.html, "escape", wraps=mailgun_templates.html.escape) as escape:
            converted = convert_text("{{#if a}}" + "&" * 2_000_000)

        assert converted.unsupported
        assert max(len(call.args[0]) for call in escape.call_args_list) <= 1_000_000
        assert len(converted.text) <= 5_000_000

    @parameterized.expand(
        [
            ("many_values", "<p>{{x}}</p>" * 60_000),
            ("long_in_liquid_units", "🧾" * 2_500_001),
        ]
    )
    def test_a_template_that_converts_too_large_stays_plain_text(self, _name: str, source: str) -> None:
        converted = convert_text(source)

        assert converted.too_large
        assert "variables." not in converted.text

    def test_too_many_values_stop_before_any_is_converted(self) -> None:
        with patch.object(mailgun_templates._Converter, "_values") as values:
            converted = convert_text("{{x}}" * 400_000)

        assert converted.too_large
        values.assert_not_called()
