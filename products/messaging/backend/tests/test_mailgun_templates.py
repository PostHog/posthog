import json
from pathlib import Path

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports import mailgun_templates
from products.messaging.backend.provider_imports.mailgun_templates import convert_text, convert_version

ESCAPED_X = '{{ variables.x | join: "," }}'
RENDER_CASES = json.loads((Path(__file__).parent / "fixtures" / "mailgun_template_renders.json").read_text())


class TestMailgunTemplateConversion(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in RENDER_CASES])
    def test_converted_templates_match_the_rendered_fixture(self, _name: str, case: dict) -> None:
        assert convert_text(case["template"], engine=case["engine"]).text == case["liquid"]

    @parameterized.expand(
        [
            ("text", "handlebars", "<p>{{x}}</p>", f"<p>{ESCAPED_X}</p>"),
            ("spaces", "handlebars", "<p>{{ x }}</p>", f"<p>{ESCAPED_X}</p>"),
            ("raw_in_text", "handlebars", "<p>{{{x}}}</p>", '<p>{{ variables.x | join: "," | raw }}</p>'),
            (
                "handlebars_link",
                "handlebars",
                '<a href="{{x}}" title="{{#if x}}y{{/if}}">',
                '<a href="{{ variables.x | join: &quot;,&quot; }}" title="{% if '
                "variables.x != nil and variables.x != false and variables.x != 0 and variables.x.length != 0 or "
                'variables.x != empty %}y{% endif %}">',
            ),
            (
                "condition_that_ends_the_attribute",
                "handlebars",
                '<a href="{{#equal x "y"}}a">{{else}}b">{{/equal}}',
                '<a href="{% assign text1 = variables.x | join: &quot;,&quot; | append: &quot;&quot; %}'
                '{% if text1 == &quot;y&quot; %}a">{% else %}b">{% endif %}',
            ),
            (
                "recipient_variable_in_a_link",
                "handlebars",
                '<a href="%recipient.x%" title="z">',
                '<a href="{{ variables.x | join: &quot;,&quot; }}" title="z">',
            ),
            (
                "after_a_style",
                "handlebars",
                "<style>p{}</style><p>{{x}}</p>",
                f"<style>p{{}}</style><p>{ESCAPED_X}</p>",
            ),
            (
                "whole_unquoted_attributes",
                "handlebars",
                "<a href={{x}} title=%recipient.x%><a href=%unsubscribe_url%>",
                '<a href="{{ variables.x | join: &quot;,&quot; }}" title="{{ variables.x | join: &quot;,&quot; }}">'
                '<a href="{{ unsubscribe_url }}">',
            ),
            (
                "in_the_title_and_after_a_script",
                "handlebars",
                "<title>{{x}}</title><script>a</script><p>{{x}}</p>",
                f"<title>{ESCAPED_X}</title><script>a</script><p>{ESCAPED_X}</p>",
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
            ("helper", "{{lookup a b}}", "{{lookup a b}}"),
            ("parent_path_at_the_top", "{{../x}}", "{{../x}}"),
            ("sendgrid_helper", '{{formatDate x "YYYY"}}', '{{formatDate x "YYYY"}}'),
            ("part_of_an_unquoted_attribute", "<a href=/{{x}}>", "{{x}}"),
            ("start_of_an_unquoted_attribute", "<a href={{x}}/a>", "{{x}}"),
            ("raw_unquoted_attribute", "<a href={{{x}}}>", "{{{x}}}"),
            ("unquoted_event_handler", "<a onclick={{x}} >", "{{x}}"),
            ("unquoted_attribute_after_a_script_comment", "<script><!--</script><a href={{x}}>", "{{x}}"),
            ("attribute_name", '<a {{x}}="y">', "{{x}}"),
            ("event_handler", '<a onclick="{{x}}">', "{{x}}"),
            ("style_attribute", '<p style="color: {{x}}">', "{{x}}"),
            ("raw_in_an_attribute", '<a title="{{{x}}}">', "{{{x}}}"),
            ("tag_name", "<{{x}}>", "{{x}}"),
            ("recipient_variable_named_size", "%recipient.size%", "%recipient.size%"),
            ("no_break_space_inside_an_unquoted_value", '<img alt=x\u00a0title="{{x}}">', "{{x}}"),
            ("value_under_a_lookup", '{{#if (lookup flags "enabled") includeZero=true}}{{x}}{{/if}}', "{{x}}"),
            ("after_a_script_that_hides_its_end", "<script><!--<script></script>--></script><p>{{x}}</p>", "{{x}}"),
            ("after_a_script_in_an_svg", """<svg><script><a title="</script>" onclick="f('{{x}}')">""", "{{x}}"),
            (
                "a_closing_tag_with_a_long_s_in_a_script",
                """<script>var a="</\u017fcript>"; f({{x}})</script>""",
                "{{x}}",
            ),
            ("after_a_title_in_an_svg", """<svg><title/></svg><a onclick="f('{{x}}')">""", "{{x}}"),
            ("raw_in_the_title", "<title>{{{x}}}</title>", "{{{x}}}"),
            ("after_the_start_of_a_closing_title", "<title></titl{{x}}></title>", "{{x}}"),
            ("a_loop_that_opens_a_comment_in_a_script", "<script><!{{#each a}}-{{/each}}</script>", "{{#each a}}"),
            ("script", "<script>var x = {{x}};</script>", "{{x}}"),
            ("style", "<style>p { color: {{x}} }</style>", "{{x}}"),
            ("html_comment", "<!-- {{x}} -->", "{{x}}"),
            ("recipient_variable_in_a_script", "<script>%recipient.x%</script>", "%recipient.x%"),
        ]
    )
    def test_a_handlebars_tag_without_a_faithful_liquid_form_stays_as_written(
        self, _name: str, source: str, kept: str
    ) -> None:
        converted = convert_text(source + "<p>{{y}}</p>")

        assert kept in converted.unsupported
        assert kept in converted.text
        assert "variables.x" not in converted.text

    @parameterized.expand(
        [
            ("unclosed", "handlebars", "a {{ b"),
            ("unclosed_block", "handlebars", "{{#if a}}<img src=x onerror=alert(1)>"),
            ("loop", "go", "{{range .Items}}x{{end}}"),
            ("go_comment_with_a_tab", "go", "{{-\t/* c */ -}}<img src=x onerror=alert(1)>"),
            ("go_trim", "go", "{{- .x -}}"),
            ("backslash_before_a_go_tag", "go", '\\{{printf "<img src=x onerror=alert(1)>"}}'),
            ("go_link", "go", '<a href="{{.x}}">'),
            ("go_data_attribute", "go", '<a data-href="{{.x}}">'),
            ("go_meta_refresh", "go", '<meta http-equiv="refresh" content="0;url={{.x}}">'),
            ("go_plain_attribute", "go", '<a title="{{.x}}">'),
            ("go_size_property", "go", "<p>{{.Order.size}}</p>"),
            ("go_after_a_comment_in_a_script", "go", "<script><!--</script><p>{{.x}}</p>"),
        ]
    )
    def test_a_go_template_or_invalid_handlebars_stays_as_text(self, _name: str, engine: str, source: str) -> None:
        converted = convert_text(source, engine=engine)  # type: ignore[arg-type]

        assert converted.unsupported or converted.malformed
        assert "variables." not in converted.text
        assert "<img" not in converted.text and "<script" not in converted.text
        assert "{{" not in converted.text.replace('{{ "{{" }}', "").replace('{{ "{%" }}', "")

    def test_a_template_kept_as_text_has_a_note(self) -> None:
        converted = convert_version({"template": "<p>{{name}}</p><p>{{lookup a b}}</p>", "headers": {"Subject": "Hi"}})

        assert converted.html == '<p>{{ variables.name | join: "," }}</p><p>{% raw %}{{lookup a b}}{% endraw %}</p>'
        assert any("can't convert {{lookup a b}}, so the email shows it as written" in note for note in converted.notes)

    @parameterized.expand(
        [
            ("fixed", "%recipient_email%", True, ESCAPED_X.replace("variables.x", "variables.recipient_email")),
            ("custom", "%recipient.first-name%", True, ESCAPED_X.replace("variables.x", "variables.first-name")),
            ("custom_text", "%recipient.city%", False, '{{ variables.city | join: "," }}'),
            ("custom_with_space_stays", "%recipient.a b%", True, "%recipient.a b%"),
            ("unsubscribe_in_a_link", 'href="%unsubscribe_url%"', True, 'href="{{ unsubscribe_url }}"'),
            ("percent_signs_alone", "100% of 50%", True, "100% of 50%"),
            ("unsubscribe_email_stays", "%unsubscribe_email%", True, "%unsubscribe_email%"),
            ("triple_in_subject_has_no_raw", "{{{x}}}", False, ESCAPED_X),
            (
                "after_raw_html",
                "{{{a}}}%recipient.x%",
                True,
                '{{ variables.a | join: "," | raw }}{{ variables.x | join: "," | escape | replace: "=", "&amp;#x3D;" | replace: "`", "&amp;#x60;" | raw }}',
            ),
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
            (
                "invalid_handlebars",
                {"template": "<p>{{#if a}}x</p>"},
                "isn't valid Handlebars, so it appears as plain text",
            ),
            ("go", {"template": "{{.x}}", "engine": "go"}, "maps may print their keys in a different order"),
        ]
    )
    def test_notes_name_what_to_review(self, _name: str, version: dict, expected: str) -> None:
        assert any(expected in note for note in convert_version(version).notes)

    def test_a_go_value_prints_lists_and_maps_the_go_way(self) -> None:
        converted = convert_text("<p>{{.x}}</p>", engine="go").text

        assert '{% if go_value1 == "[" %}[' in converted
        assert "map[{% for pair in variables.x %}" in converted

    def test_a_go_value_used_again_is_only_turned_into_json_once(self) -> None:
        converted = convert_text("<p>{{.x}} {{.x}} {{.y}} {{.x}}</p>", engine="go").text

        assert converted.count("variables.x | json") == 1
        assert converted.count("variables.y | json") == 1

    def test_a_go_value_used_first_through_a_mailgun_variable_still_reads_its_kind(self) -> None:
        converted = convert_text("%recipient.x% {{.x}}", engine="go").text

        assert converted.startswith("{% assign go_value1 = variables.x | json | slice: 0 %}")

    def test_a_blank_engine_with_go_syntax_reads_as_go(self) -> None:
        assert "variables.Name" in convert_version({"engine": "", "template": "{{.Name}}"}).html

    def test_many_values_scan_in_linear_time(self) -> None:
        converted = convert_text("<p>{{x}}</p>" * 30_000)

        assert converted.text.count("variables.x") == 30_000

    def test_a_huge_template_is_cut_before_its_fallback_text_is_built(self) -> None:
        with patch.object(mailgun_templates.html, "escape", wraps=mailgun_templates.html.escape) as escape:
            converted = convert_text("{{#if a}}" + "&" * 2_000_000)

        assert converted.malformed
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

    @parameterized.expand([("handlebars",), ("go",)])
    def test_too_many_values_stop_before_any_is_converted(self, engine: str) -> None:
        converted = convert_text("{{x}}" * 400_000, engine=engine)  # type: ignore[arg-type]

        assert converted.too_large
        assert "variables." not in converted.text
