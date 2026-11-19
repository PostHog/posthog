import json
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports.sendgrid_templates import convert_version, plain_text_from_html

RENDERS = json.loads((Path(__file__).parent / "fixtures" / "sendgrid_template_renders.json").read_text())


class TestSendGridTemplateConversion(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in RENDERS])
    def test_produces_the_liquid_the_render_tests_prove(self, _name: str, case: dict[str, Any]) -> None:
        if case.get("text"):
            assert convert_version({"subject": case["source"]}).subject == case["liquid"]
        else:
            converted = convert_version(
                {"html_content": case["source"], "generate_plain_content": False, "plain_content": "p"}
            )
            assert converted.html == case["liquid"]

    @parameterized.expand(
        [
            ("unclosed_block", "{{#if a}}unclosed"),
            ("condition", "<p>{{#if vip}}Hi{{else}}Hello{{/if}}</p>"),
            ("condition_on_an_empty_object", "{{#if settings}}{{name}}{{/if}}"),
            ("loop_over_an_object", "{{#each orders}}{{this.name}}{{/each}}"),
            ("this", "<p>{{this}}</p>"),
            ("stray_close", "{{/if}}"),
            ("partial", "{{> partial}}"),
            ("helper", "{{helper a b}}"),
            ("section", "{{#section}}x{{/section}}"),
            ("loop_value", "{{#each xs}}{{@index}}{{/each}}"),
            ("parent_path", "{{#each xs}}{{../name}}{{/each}}"),
            ("format_date", "{{formatDate t}}"),
            ("insert", '{{insert name "default=x"}}'),
            ("else_if", "{{#if a}}A{{else if b}}B{{/if}}"),
            ("unless", "{{#unless a}}A{{/unless}}"),
            ("with", "{{#with a}}{{b}}{{/with}}"),
            ("lookup", '{{#if (lookup permissions "allow")}}{{token}}{{/if}}'),
            ("key_loop", "{{#each o}}{{@key}}={{this}}{{/each}}"),
            ("tilde", "<p>{{~name}}</p>"),
            ("spaced_tilde", '<a href="https://example.com">{{ ~#if allow}}{{token}}{{/if}}</a>'),
            ("entity", '<a href="{{&#35;if allow}}https://example.com">{{token}}</a>{{&#47;if}}'),
            ("comment_tag", "<p>{ {{~!c}}% echo person.properties.secret %}</p>"),
            ("block_in_a_comment", "<!-- {{#if allow}} --><p>{{token}}</p><!-- {{/if}} -->"),
            ("block_after_a_stray_angle_bracket", "x < <!--{{#if allow}}-->>{{token}} <i<!--{{/if}}-->b> y"),
            ("block_in_an_attribute", '<a href="{{#if allow}}https://example.com">{{token}}</a>{{/if}}'),
            ("block_in_a_tag", '<a {{#if allow}} href="https://example.com">{{token}}</a>{{/if}}'),
            ("block_in_a_link", '<a href="https://example.com">{{#if allow}}{{token}}{{/if}}</a>'),
            ("block_in_a_style_block", "<style>{{#if dark}}p{color:#fff}{{/if}}</style><p>{{token}}</p>"),
            ("value_in_an_unquoted_attribute", "<a href={{token}}>x</a>"),
            ("value_in_an_event_handler", '<a onclick="{{token}}">x</a>'),
            ("value_as_an_attribute_name", "<p {{token}}>x</p>"),
            ("unsubscribe_tag_in_a_string", '{{ insert name "default=<%body%>" }}'),
            ("event_handler_hidden_by_an_angle_bracket", '<a title="a>b" onclick="{{first_name}}">x</a>'),
            ("event_handler_hidden_by_a_tag_like_value", '<a title="<%%>" onclick="{{first_name}}">x</a>'),
            ("brace_before_a_body_tag", "x{<%body%>y"),
            (
                "unsubscribe_tag_beside_a_block_in_an_attribute",
                '<a href="<%subject%>{{#if allow}}u">{{token}}</a>{{/if}}',
            ),
            ("unsubscribe_tag_guarded_by_a_helper", '{{#if (lookup p "a")}}x<%body%>y{{/if}}'),
            ("deep_nesting", "".join(f"{{{{#with {'a' * 1900}}}}}" for _ in range(40)) + "{{this}}" * 500),
        ]
    )
    def test_anything_but_a_supported_form_keeps_the_whole_template_as_text(self, _name: str, html: str) -> None:
        converted = convert_version({"html_content": html})

        assert "this template's tags" in " ".join(converted.notes)
        for part in (converted.html, converted.text):
            assert "variables." not in part
            assert "{% if" not in part
            assert "unsubscribe_url" not in part
            assert "\x00" not in part

    @parameterized.expand(
        [
            ("value", "<p>Hi {{ name }}</p>", "{{ variables.name |"),
            ("raw_value", "<p>{{{ body.html }}}</p>", '{{ variables.body.html | join: "," | raw }}'),
            ("value_in_a_plain_attribute", '<a href="https://example.com/?id={{id}}">Go</a>', "variables.id |"),
            ("unsubscribe_link", '<a href="{{{unsubscribe}}}">Leave</a>', "{{ unsubscribe_url }}"),
            (
                "unsubscribe_tag_in_an_attribute",
                '<a href="<%asm_group_unsubscribe_raw_url%>">Leave</a>',
                "{{ unsubscribe_url }}",
            ),
        ]
    )
    def test_supported_forms_convert(self, _name: str, html: str, expected: str) -> None:
        converted = convert_version({"html_content": html})

        assert expected in converted.html
        assert not any("this template's tags" in note for note in converted.notes)

    def test_plain_text_keeps_a_stray_brace_from_joining_a_tag(self) -> None:
        converted = convert_version({"html_content": "<p>{<b>{{name}}</b></p>"})

        assert "{{{" not in converted.text
        assert converted.text.endswith('{{ variables.name | join: "," }}')

    @parameterized.expand(
        [
            ("Dear -name-", 'Dear {{ variables.name | default: "-name-" | raw }}'),
            ("well-known-word and x-y-z", "well-known-word and x-y-z"),
            ("<style>a{margin:-a-}</style>", "<style>a{margin:-a-}</style>"),
            ("{{not}} handlebars", "{% raw %}{{not}}{% endraw %} handlebars"),
            ("<%body%>", "{{ variables.body | raw }}"),
            ("<%asm_preferences_raw_url%>", "{{ unsubscribe_url }}"),
            (
                "<title>{{ person.properties.secret }}</title><!-- {% x %} -->",
                "<title>{% raw %}{{ person.properties.secret }}{% endraw %}</title><!-- {% raw %}{% x %}{% endraw %} -->",
            ),
            (
                "&lt;%asm_group_unsubscribe_url%&gt;",
                '<a href="{{ unsubscribe_url }}">Unsubscribe From This List</a>',
            ),
        ]
    )
    def test_legacy_templates(self, source: str, html: str) -> None:
        converted = convert_version(
            {"html_content": source, "generate_plain_content": False, "plain_content": ""}, generation="legacy"
        )
        assert converted.html.strip() == html

    @parameterized.expand(
        [
            ("before_a_body_tag", "x{<%body%>y"),
            ("before_an_escaped_body_tag", "x{&lt;%body%&gt;y"),
            ("before_a_tag", "x{-name-y"),
        ]
    )
    def test_a_legacy_template_with_a_brace_before_a_tag_stays_as_text(self, _name: str, html: str) -> None:
        converted = convert_version({"html_content": html, "generate_plain_content": False}, generation="legacy")

        assert "{{{" not in converted.html
        assert "variables." not in converted.html
        assert "this template's tags" in " ".join(converted.notes)

    def test_only_a_template_with_other_tag_marks_gets_the_note_about_them(self) -> None:
        version = {"subject": "<%subject%>", "generate_plain_content": False}
        assert "%name%" not in " ".join(
            convert_version({**version, "html_content": "<%body%> 100% #fff"}, generation="legacy").notes
        )
        assert "%name%" in " ".join(
            convert_version({**version, "html_content": "Hi %name%"}, generation="legacy").notes
        )

    def test_plain_text_is_built_from_the_html_when_sendgrid_would_build_it(self) -> None:
        html = (
            "<html><head><style>p{color:red}</style></head><body><p>Hi {{ variables.n | raw }}</p>"
            '{% if variables.a > 1 %}<a href="{{ unsubscribe_url }}">Leave</a>{% endif %}<br>Tom &amp; Ann<br>'
            "&#123;&#123; person.properties.secret &#125;&#125; <b>{</b>{ x }}</body></html>"
        )

        assert plain_text_from_html(html) == (
            "Hi {{ variables.n }}\n{% if variables.a > 1 %}Leave ({{ unsubscribe_url }}){% endif %}\nTom & Ann\n"
            "{% raw %}{{ person.properties.secret }}{% endraw %} {% raw %}{{ x }}{% endraw %}"
        )

    def test_plain_text_prints_values_without_html_escaping(self) -> None:
        converted = convert_version({"html_content": '<p>{{name}} <a href="https://example.com/?a={{id}}">Go</a></p>'})

        assert converted.text == (
            '{{ variables.name | join: "," }} Go (https://example.com/?a={{ variables.id | join: "," }})'
        )

    def test_a_tag_kept_as_text_stays_text_in_the_plain_part(self) -> None:
        converted = convert_version({"html_content": '<p>{{helper endraw" | append: person.properties.secret}}</p>'})

        assert converted.html == '<p>{{ "{{" }}helper endraw" | append: person.properties.secret}}</p>'
        assert converted.text == '{{ "{{" }}helper endraw" | append: person.properties.secret}}'

    def test_plain_text_source_cannot_stand_in_for_a_held_tag(self) -> None:
        text = plain_text_from_html("<p>{% raw %}{{ person.properties.secret }}{% endraw %} \x011\x01</p>")

        assert text == "{% raw %}{{ person.properties.secret }}{% endraw %} 1"

    @parameterized.expand(
        [
            ("unsubscribe_placeholder", "<p>{\x00asm:\x00{ person.properties.secret }}</p>"),
            ("plain_text_slot", "<p>{\x01{ person.properties.secret }}</p>"),
        ]
    )
    def test_source_text_cannot_pass_for_a_converter_marker(self, _name: str, html: str) -> None:
        converted = convert_version({"html_content": html})

        assert "{{ person.properties.secret }}" not in converted.html
        assert "{{ person.properties.secret }}" not in converted.text

    def test_plain_text_keeps_a_literal_raw_filter_from_closing_its_raw_block(self) -> None:
        html = "<p>{{#weird {% end | rawraw %}{% echo person.properties.secret %}{% raw %} }}</p>"

        converted = convert_version({"html_content": html})

        assert converted.text == f"{{% raw %}}{html[3:-4]}{{% endraw %}}"

    def test_a_legacy_comment_with_a_character_that_lowercases_longer_keeps_tags_as_text(self) -> None:
        converted = convert_version(
            {"html_content": "<!--İ-->{{ person.properties.secret }}", "generate_plain_content": False},
            generation="legacy",
        )

        assert converted.html == "<!--İ-->{% raw %}{{ person.properties.secret }}{% endraw %}"

    def test_many_unclosed_tags_convert_quickly(self) -> None:
        assert convert_version({"html_content": "{{" * 200_000, "generate_plain_content": False}).html
