import re
import json
from pathlib import Path
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports import mailgun_templates
from products.messaging.backend.provider_imports.mailgun_templates import convert_text, convert_version

ESCAPED_X = '{{ variables.x | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}'
RENDER_CASES = json.loads((Path(__file__).parent / "fixtures" / "mailgun_template_renders.json").read_text())


class TestMailgunTemplateConversion(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in RENDER_CASES])
    def test_converted_templates_match_the_rendered_fixture(self, _name: str, case: dict) -> None:
        assert convert_text(case["template"], engine=case["engine"]).text == case["liquid"]

    def test_an_entity_in_a_go_comparison_literal_stays_text(self) -> None:
        converted = convert_text('{{if eq .x "&quot; or person.properties.vip or &quot;"}}a{{end}}', engine="go")

        assert "{% if" not in converted.text

    @parameterized.expand(
        [
            ("helper_with_arguments", "{{lookup a b}}", ""),
            ("partial", "{{> footer}}", ""),
            (
                "subexpression_keeps_body",
                "{{#if (eq a b)}}x{{/if}}",
                "x",
            ),
            (
                "entity_in_an_equal_literal_stays_text",
                '{{#equal a "&quot; or person.properties.vip or &quot;"}}x{{/equal}}',
                "x",
            ),
            (
                "liquid_delimiter_in_a_path",
                "{{#if [a%}b]}}yes{{/if}}",
                "yes",
            ),
            ("brace_before_an_escaped_tag", "{\\{{x}}", '{{ "{" }}{{ "{{" }}x}}'),
            ("entities_in_an_escaped_tag", "\\{{&lt;script&gt;}}", '{{ "{{" }}&lt;script&gt;}}'),
            ("stray_closer", "x{{/if}}", "x"),
            ("stray_else", "x{{else}}", "x"),
            ("unclosed_opening", "a {{ b", 'a {{ "{{" }} b'),
            ("endraw_inside", "{{foo endraw bar}}", ""),
            (
                "quoted_greater_than_keeps_the_tag_open",
                '<a title="5 > 3" href={{url}}>',
                '<a title="5 > 3" href={{ variables.url | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}>',
            ),
            (
                "a_value_named_like_else_is_not_a_branch",
                "{{#if a}}<a title={{else-label}} href={{url}}>{{/if}}",
                "{% if variables.a and variables.a.length != 0 and variables.a != 0 %}<a title="
                '{{ variables.else-label | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }} href='
                '{{ variables.url | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}>{% endif %}',
            ),
            (
                "a_value_named_else_with_a_trailing_dash_is_not_a_branch",
                "{{#if a}}<a title={{else-}} href={{url}}>{{/if}}",
                "{% if variables.a and variables.a.length != 0 and variables.a != 0 %}<a title="
                '{{ variables.else- | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }} href='
                '{{ variables.url | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}>{% endif %}',
            ),
            (
                "either_branch_leaving_a_tag_open_keeps_the_value_escaped",
                "{{#if a}}<a title={{else}}<a>{{/if}}{{url}}",
                "{% if variables.a and variables.a.length != 0 and variables.a != 0 %}<a title={% else %}<a>{% endif %}"
                '{{ variables.url | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}',
            ),
            (
                "a_block_that_renders_nothing_keeps_the_value_escaped",
                "<a title={{#if a}}>ok{{/if}}{{x}}>",
                "<a title={% if variables.a and variables.a.length != 0 and variables.a != 0 %}>ok{% endif %}"
                '{{ variables.x | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}>',
            ),
            (
                "unclosed_block_is_closed",
                "{{#if a}}x",
                "{% if variables.a and variables.a.length != 0 and variables.a != 0 %}x{% endif %}",
            ),
        ]
    )
    def test_what_cannot_convert_stays_text_that_liquid_can_parse(self, _name: str, source: str, expected: str) -> None:
        assert convert_text(source).text == expected

    @parameterized.expand(
        [
            ("fixed_html", "%recipient_email%", True, ESCAPED_X.replace("variables.x", "variables.recipient_email")),
            ("custom_html", "%recipient.first-name%", True, ESCAPED_X.replace("variables.x", "variables.first-name")),
            ("custom_with_space_stays", "%recipient.a b%", True, "%recipient.a b%"),
            ("custom_text", "%recipient.city%", False, "{{ variables.city }}"),
            ("dotted_key_is_one_name", "%recipient.a.b%", True, ESCAPED_X.replace("variables.x", 'variables["a.b"]')),
            ("value_inside_a_tag", '<a href="%recipient.x%">', True, f'<a href="{ESCAPED_X}">'),
            ("name_with_a_backslash_stays", "%recipient.a\\b%", True, "%recipient.a\\b%"),
            ("name_with_an_entity_stays", "%recipient.a&amp;b%", True, "%recipient.a&amp;b%"),
            ("unsubscribe", 'href="%unsubscribe_url%"', True, 'href="{{ unsubscribe_url }}"'),
            ("percent_signs_alone", "100% of 50%", True, "100% of 50%"),
            ("unsubscribe_email_stays", "%unsubscribe_email%", True, "%unsubscribe_email%"),
            ("triple_in_subject_has_no_raw", "{{{x}}}", False, "{{ variables.x }}"),
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
            ("unclosed", {"template": "{{#if a}}x"}, "never closed"),
            ("go_value_in_a_tag", {"engine": "go", "template": '<a href="{{.URL}}">x</a>'}, "rewrite them in Liquid"),
        ]
    )
    def test_notes_name_what_to_review(self, _name: str, version: dict, expected: str) -> None:
        assert any(expected in note for note in convert_version(version).notes)

    def test_a_blank_engine_with_go_syntax_reads_as_go(self) -> None:
        assert (
            ESCAPED_X.replace("variables.x", "variables.Name")
            in convert_version({"engine": "", "template": "{{.Name}}"}).html
        )

    @parameterized.expand([("handlebars", "{{!"), ("handlebars_block", "{{!--"), ("go", "{{/*"), ("go_trim", "{{- /*")])
    def test_unclosed_comments_look_for_their_end_once(self, _name: str, opener: str) -> None:
        counted = [(start, _CountedSearch(end)) for start, end in mailgun_templates._COMMENTS]

        with patch.object(mailgun_templates, "_COMMENTS", tuple(counted)):
            converted = convert_text(opener * 20000)

        assert sum(end.calls for _, end in counted) <= len(counted)
        assert not converted.too_large

    @parameterized.expand(
        [
            ("quoted_link", '<a href="{{.U}}">x</a>', "{{.U}}"),
            ("unquoted_link", "<a href={{.U}}>x</a>", "{{.U}}"),
            ("attribute_name", '<a {{.A}}="x">x</a>', "{{.A}}"),
            ("event_handler", '<a onclick="send({{.X}})">x</a>', "{{.X}}"),
            ("script", "<script>var x = {{.X}};</script>", "{{.X}}"),
            ("style", "<style>p { color: {{.C}} }</style>", "{{.C}}"),
            ("script_with_a_lookalike_end_tag", "<script>/* </scriptx> */ var x = {{.X}};</script>", "{{.X}}"),
            ("script_after_a_stray_less_than", "a<3 <script>var x = {{.X}};</script>", "{{.X}}"),
            ("after_a_script_ends", "<script>x</script><p>{{.X}}</p>", "{{.X}}"),
            ("after_many_scripts", "<SCRIPT></SCRIPT>" * 10000 + "{{.X}}", "{{.X}}"),
            ("after_an_html_comment", '<!-- " --><a href="{{.U}}">x</a>', "{{.U}}"),
        ]
    )
    def test_a_go_value_where_go_escapes_by_context_is_left_out(self, _name: str, source: str, value: str) -> None:
        converted = convert_version({"engine": "go", "template": source})

        assert value not in converted.html
        assert "variables." not in converted.html
        assert any("rewrite them in Liquid" in note for note in converted.notes)

    @parameterized.expand(
        [
            ("markup", '{{printf "<script>" .x}} {{.User}}'),
            ("entity_encoded_markup", '{{printf "&lt;img src=x&gt;" .x}} {{.User}}'),
        ]
    )
    def test_a_tag_that_cannot_convert_is_left_out_of_the_body(self, _name: str, source: str) -> None:
        converted = convert_version({"engine": "go", "template": source})

        assert "printf" not in converted.html
        assert "variables.User" in converted.html
        assert any("left out of the email body" in note for note in converted.notes)

    def test_a_tag_that_cannot_convert_stays_as_text_in_the_subject(self) -> None:
        assert convert_text("{{lookup a b}}", is_html=False).text == '{{ "{{" }}lookup a b}}'

    def test_a_go_value_in_page_text_converts(self) -> None:
        converted = convert_text("<p>{{.Name}}</p>", engine="go")

        assert ESCAPED_X.replace("variables.x", "variables.Name") in converted.text

    def test_a_long_comment_renders_nothing(self) -> None:
        source = "{{!-- " + "x" * 30000 + " {{secret}} --}}after"

        assert convert_text(source).text == "after"

    def test_a_template_with_too_many_tags_stops_before_converting(self) -> None:
        assert convert_text("{{" * 50001).too_large

    def test_unclosed_braces_scan_in_linear_time(self) -> None:
        assert convert_text("{{ " * 20000).text.count('{{ "{{" }}') == 20000

    @parameterized.expand(
        [
            ("many_loops", "{{#each xs}}{{/each}}" * 32000),
            ("deep_long_paths", "".join(f"{{{{#with {chr(97 + i % 26) * 200}}}}}" for i in range(400))),
            ("deep_nesting", "{{#with a}}" * 101),
            ("recipient_variables_expand_past_the_limit", "%recipient.x%" * 70000),
        ]
    )
    def test_a_template_that_converts_too_large_stays_plain_text(self, _name: str, source: str) -> None:
        converted = convert_text(source)

        assert converted.too_large
        assert converted.text == source.replace("{{", '{{ "{{" }}')


class _CountedSearch:
    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern
        self.calls = 0

    def search(self, *args: Any) -> re.Match[str] | None:
        self.calls += 1
        return self.pattern.search(*args)
