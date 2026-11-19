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
            ("{{#if a}}unclosed", "{% raw %}{{#if a}}{% endraw %}unclosed", "valid Handlebars"),
            ("{{/if}}", "{% raw %}{{/if}}{% endraw %}", "valid Handlebars"),
            ("{{> partial}}", "{% raw %}{{> partial}}{% endraw %}", "{{> partial}}"),
            ("{{helper a b}}", "{% raw %}{{helper a b}}{% endraw %}", "{{helper a b}}"),
            (
                "{{#section}}x{{/section}}",
                "{% raw %}{{#section}}{% endraw %}x{% raw %}{{/section}}{% endraw %}",
                "section",
            ),
            ("{{@../index}}", "{% raw %}{{@../index}}{% endraw %}", "index"),
            (
                "{{formatDate t fmt}}",
                '{{ variables.t | date: "%Y-%m-%dT%H:%M:%S.%LZ", 0 | join: "," | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}',
                "fmt",
            ),
            ("{{{Weblink}}}", "", "view in browser"),
            (
                '{{formatDate t "YYYY-MM-DD [at] HH:mm"}}',
                '{% raw %}{{formatDate t "YYYY-MM-DD [at] HH:mm"}}{% endraw %}',
                "formatDate",
            ),
            ('{{formatDate t "MMMM Do, YYYY"}}', '{% raw %}{{formatDate t "MMMM Do, YYYY"}}{% endraw %}', "formatDate"),
        ]
    )
    def test_what_cannot_convert_stays_visible_and_gets_a_note(self, source: str, html: str, note: str) -> None:
        converted = convert_version({"html_content": source, "generate_plain_content": False, "plain_content": "p"})

        assert converted.html == html
        assert note in " ".join(converted.notes)

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

    @parameterized.expand(
        [
            ("in_a_comment", "<!-- {{#if allow}} --><p>{{token}}</p><!-- {{/if}} -->", "comment"),
            ("after_a_stray_angle_bracket", "x < <!--{{#if allow}}-->>{{token}} <i<!--{{/if}}-->b> y", "comment"),
            ("in_an_attribute", '<a href="{{#if allow}}https://example.com">{{token}}</a>{{/if}}', "attribute"),
            ("in_a_tag", '<a {{#if allow}} href="https://example.com">{{token}}</a>{{/if}}', "attribute"),
            ("in_a_link", '<a href="https://example.com">{{#if allow}}{{token}}{{/if}}</a>', "link"),
            (
                "entity_spelled_block",
                '<a href="{{&#35;if allow}}https://example.com">{{token}}</a>{{&#47;if}}',
                "attribute",
            ),
            ("spaced_tilde_block", '<a href="https://example.com">{{ ~#if allow}}{{token}}{{/if}}</a>', "link"),
            ("in_a_style_block", "<style>{{#if dark}}p{color:#fff}{{/if}}</style><p>{{token}}</p>", "style"),
            ("unsubscribe_tag_in_a_string", '{{ insert name "default=<%body%>" }}', "inside another tag"),
            ("unsubscribe_tag_in_a_comparison", '{{#equals a "<%subject%>"}}x{{/equals}}', "inside another tag"),
        ]
    )
    def test_a_tag_in_an_unusual_place_keeps_the_whole_template_as_text(self, _name: str, html: str, why: str) -> None:
        converted = convert_version({"html_content": html})

        assert "variables.token" not in converted.html + converted.text
        assert "{% if" not in converted.html + converted.text
        assert why in " ".join(converted.notes)
        assert "\x00" not in converted.html + " ".join(converted.notes)

    def test_a_tag_kept_as_text_stays_text_in_the_plain_part(self) -> None:
        converted = convert_version({"html_content": '<p>{{helper endraw" | append: person.properties.secret}}</p>'})

        assert converted.html == '<p>{{ "{{" }}helper endraw" | append: person.properties.secret}}</p>'
        assert converted.text == '{{ "{{" }}helper endraw" | append: person.properties.secret}}'

    def test_plain_text_source_cannot_stand_in_for_a_held_tag(self) -> None:
        text = plain_text_from_html("<p>{% raw %}{{ person.properties.secret }}{% endraw %} \x011\x01</p>")

        assert text == "{% raw %}{{ person.properties.secret }}{% endraw %} 1"

    def test_a_dropped_comment_cannot_join_text_into_a_liquid_tag(self) -> None:
        converted = convert_version({"html_content": "<p>{ {{~!c}}% echo person.properties.secret %}</p>"})

        assert converted.html == '<p>{{ "{" }}% echo person.properties.secret %}</p>'
        assert converted.text == '{{ "{" }}% echo person.properties.secret %}'

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

    def test_plain_text_drops_a_literal_attribute_whole(self) -> None:
        converted = convert_version(
            {"html_content": "<p title=\"{{default name '> {{ person.properties.secret }}'}}\">x</p>"}
        )

        assert converted.text == "x"

    def test_a_loop_over_an_object_s_keys_stays_as_text_with_a_note(self) -> None:
        converted = convert_version(
            {"html_content": "{{#each o}}{{@key}}={{this}}{{/each}}", "generate_plain_content": False}
        )

        assert (
            converted.html
            == "{% raw %}{{#each o}}{% endraw %}{% raw %}{{@key}}{% endraw %}={% raw %}{{this}}{% endraw %}{% raw %}{{/each}}{% endraw %}"
        )
        assert "{{#each o}}" in " ".join(converted.notes)

    def test_an_inverted_key_loop_kept_as_text_keeps_its_branches_in_order(self) -> None:
        source = "{{^each o}}empty{{else}}{{@key}}={{this}}{{/each}}"

        converted = convert_version({"html_content": source, "generate_plain_content": False})

        assert converted.html.replace("{% raw %}", "").replace("{% endraw %}", "") == source

    def test_a_block_that_cannot_convert_keeps_what_it_guards_as_text(self) -> None:
        source = '{{#if (lookup permissions "allow_token")}}{{token}}{{/if}}'

        converted = convert_version({"html_content": source, "generate_plain_content": False})

        assert "variables.token" not in converted.html
        assert converted.html.replace("{% raw %}", "").replace("{% endraw %}", "") == source

    def test_a_quoted_key_is_not_a_key_lookup(self) -> None:
        converted = convert_version(
            {
                "html_content": '{{#each xs}}{{#equals kind "@key"}}{{name}}{{/equals}}{{/each}}',
                "generate_plain_content": False,
            }
        )

        assert converted.html.startswith("{% for item in variables.xs %}")

    def test_a_key_loop_kept_as_text_keeps_a_chained_condition_as_written(self) -> None:
        source = "{{#each o}}{{@key}}{{#if a}}A{{else if b}}B{{/if}}{{/each}}"

        converted = convert_version({"html_content": source, "generate_plain_content": False})

        assert converted.html.replace("{% raw %}", "").replace("{% endraw %}", "") == source

    def test_a_loop_converts_as_a_loop_over_a_list(self) -> None:
        converted = convert_version({"html_content": "{{#each xs}}{{name}}{{/each}}", "generate_plain_content": False})

        assert converted.html.startswith("{% for item in variables.xs %}")

    def test_a_legacy_comment_with_a_character_that_lowercases_longer_keeps_tags_as_text(self) -> None:
        converted = convert_version(
            {"html_content": "<!--İ-->{{ person.properties.secret }}", "generate_plain_content": False},
            generation="legacy",
        )

        assert converted.html == "<!--İ-->{% raw %}{{ person.properties.secret }}{% endraw %}"

    def test_deeply_nested_blocks_that_would_blow_up_stay_as_text_with_a_note(self) -> None:
        path = "a" * 1900
        source = "".join(f"{{{{#with {path}}}}}" for _ in range(40)) + "{{this}}" * 500 + "{{/with}}" * 40

        converted = convert_version({"html_content": source, "generate_plain_content": False})

        assert len(converted.html) < 1_000_000
        assert "nest too deeply" in " ".join(converted.notes)

    def test_many_unclosed_tags_convert_quickly(self) -> None:
        assert convert_version({"html_content": "{{" * 200_000, "generate_plain_content": False}).html
