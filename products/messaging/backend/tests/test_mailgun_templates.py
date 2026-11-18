import json
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports.mailgun_templates import convert_text, convert_version

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
            ("helper_with_arguments", "{{lookup a b}}", "{% raw %}{{lookup a b}}{% endraw %}"),
            ("partial", "{{> footer}}", "{% raw %}{{> footer}}{% endraw %}"),
            (
                "subexpression_keeps_body",
                "{{#if (eq a b)}}x{{/if}}",
                "{% raw %}{{#if (eq a b)}}{% endraw %}x{% raw %}{{/if}}{% endraw %}",
            ),
            (
                "entity_in_an_equal_literal_stays_text",
                '{{#equal a "&quot; or person.properties.vip or &quot;"}}x{{/equal}}',
                '{% raw %}{{#equal a "&quot; or person.properties.vip or &quot;"}}{% endraw %}x'
                "{% raw %}{{/equal}}{% endraw %}",
            ),
            ("stray_closer", "x{{/if}}", "x{% raw %}{{/if}}{% endraw %}"),
            ("stray_else", "x{{else}}", "x{% raw %}{{else}}{% endraw %}"),
            ("unclosed_opening", "a {{ b", 'a {{ "{{" }} b'),
            ("endraw_inside", "{{foo endraw bar}}", '{{ "{{" }}foo endraw bar}}'),
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
            ("fixed_html", "%recipient_email%", True, "{{ variables.recipient_email | raw }}"),
            ("custom_html", "%recipient.first-name%", True, "{{ variables.first-name | raw }}"),
            ("custom_with_space_stays", "%recipient.a b%", True, "%recipient.a b%"),
            ("custom_text", "%recipient.city%", False, "{{ variables.city }}"),
            ("dotted_key_is_one_name", "%recipient.a.b%", True, '{{ variables["a.b"] | raw }}'),
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
            ("go_value_in_a_tag", {"engine": "go", "template": '<a href="{{.URL}}">x</a>'}, "inside HTML tags"),
        ]
    )
    def test_notes_name_what_to_review(self, _name: str, version: dict, expected: str) -> None:
        assert any(expected in note for note in convert_version(version).notes)

    def test_a_blank_engine_with_go_syntax_reads_as_go(self) -> None:
        assert "{{ variables.Name }}" in convert_version({"engine": "", "template": "{{.Name}}"}).html

    def test_unclosed_braces_scan_in_linear_time(self) -> None:
        assert convert_text("{{ " * 20000).text.count('{{ "{{" }}') == 20000

    @parameterized.expand(
        [
            ("many_loops", "{{#each xs}}{{/each}}" * 32000),
            ("deep_long_paths", "".join(f"{{{{#with {chr(97 + i % 26) * 200}}}}}" for i in range(400))),
        ]
    )
    def test_a_template_that_converts_too_large_stays_plain_text(self, _name: str, source: str) -> None:
        converted = convert_text(source)

        assert converted.too_large
        assert converted.text == f"{{% raw %}}{source}{{% endraw %}}"
