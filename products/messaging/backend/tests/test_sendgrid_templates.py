import re
import json
import time
import tracemalloc
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports.sendgrid_handlebars import liquid_literal
from products.messaging.backend.provider_imports.sendgrid_templates import convert_version, plain_text_from_html

RENDERS = json.loads((Path(__file__).parent / "fixtures" / "sendgrid_template_renders.json").read_text())


class TestSendGridTemplateConversion(SimpleTestCase):
    @parameterized.expand([(case["name"], case) for case in RENDERS])
    def test_produces_the_liquid_the_render_tests_prove(self, _name: str, case: dict[str, Any]) -> None:
        if case.get("text"):
            assert convert_version({"subject": case["source"]}).subject == case["liquid"]
        else:
            converted = convert_version(
                {"html_content": case["source"], "generate_plain_content": False, "plain_content": "p"},
                generation=case.get("generation", "dynamic"),
            )
            assert converted.html == case["liquid"]

    @parameterized.expand(
        [
            ("this", "<p>{{this}}</p>", "{{this}}"),
            ("partial", "{{> partial}}", "{{> partial}}"),
            ("braces_in_an_unescaped_value", "{{{ a}}b }}}", "{{{ a}}b }}}"),
            ("entity_in_a_value", "<p>{{ a&quot;b }}</p>", "{{ a&quot;b }}"),
            ("deep_groups_in_a_value", "{{eq " + "(a " * 60 + "b}}", "{{eq " + "(a " * 60 + "b}}"),
            ("helper", "{{helper a b}}", "{{helper a b}}"),
            ("section", "{{#section}}x{{/section}}", "{{#section}}"),
            ("or", "{{#or a b}}x{{else}}y{{/or}}", "{{#or a b}}"),
            ("value_under_an_or", "{{#or a b}}{{token}}{{/or}}", "{{token}}"),
            ("inverted_section", "{{^items}}none{{/items}}", "{{^items}}"),
            ("loop_index_under_a_kept_each", "{{#each a}}{{#each b key=1}}{{@index}}{{/each}}{{/each}}", "{{@index}}"),
            (
                "value_under_an_each_that_stays_as_written",
                "{{#each items key=1}}<li>{{label}}</li>{{/each}}",
                "{{label}}",
            ),
            (
                "else_if_under_a_block_that_stays_as_written",
                "{{#if a includeZero=x}}A{{else if b}}B{{/if}}",
                "{{else if b}}",
            ),
            ("escaped_tag_opening_an_attribute", "\\{{<img src=x }}{{token}}", "{{token}}"),
            ("lookup", '{{#if (lookup permissions "allow")}}{{token}}{{/if}}', '{{#if (lookup permissions "allow")}}'),
            ("value_under_a_lookup", '{{#if (lookup permissions "allow")}}{{token}}{{/if}}', "{{token}}"),
            ("value_under_a_comparison_of_two_values", "{{#notEquals a b}}{{token}}{{/notEquals}}", "{{token}}"),
            ("value_under_a_comparison_with_empty_text", '{{#equals a ""}}{{token}}{{/equals}}', "{{token}}"),
            (
                "value_under_a_comparison_with_null",
                "{{#greaterThan a null}}x{{else}}{{token}}{{/greaterThan}}",
                "{{token}}",
            ),
            ("insert_default_with_an_entity", '{{insert x "default=&lt;b&gt;"}}', '{{insert x "default=&lt;b&gt;"}}'),
            ("value_under_a_comparison_with_an_entity", '{{#equals a "&lt;b&gt;"}}{{token}}{{/equals}}', "{{token}}"),
            (
                "value_under_an_else_if_that_stays_as_written",
                '{{#equals plan "gold"}}A{{else if (greaterThan spend 500)}}{{token}}{{/equals}}',
                "{{token}}",
            ),
            (
                "value_under_a_comparison_with_a_number_too_large_to_hold",
                "{{#notEquals a " + "9" * 400 + "}}{{token}}{{/notEquals}}",
                "{{token}}",
            ),
            (
                "value_under_a_lookup_with_include_zero",
                '{{#if (lookup flags "enabled") includeZero=true}}{{token}}{{/if}}',
                "{{token}}",
            ),
            ("parent_path_under_with_this", "{{#each xs}}{{#with this}}{{../name}}{{/with}}{{/each}}", "{{../name}}"),
            ("key_loop", "{{#each o}}{{@key}}={{this}}{{/each}}", "{{@key}}"),
            ("format_date_without_a_format", "{{formatDate t}}", "{{formatDate t}}"),
            ("format_date_with_an_ordinal", '{{formatDate t "Do MMM"}}', '{{formatDate t "Do MMM"}}'),
            ("format_date_day_of_the_year", '{{formatDate t "DDD"}}', '{{formatDate t "DDD"}}'),
            ("value_in_an_unquoted_attribute", "<a href=/{{token}}>x</a>", "{{token}}"),
            ("value_in_an_event_handler", '<a onclick="{{token}}">x</a>', "{{token}}"),
            ("value_as_an_attribute_name", "<p {{token}}>x</p>", "{{token}}"),
            ("value_as_a_tag_name", "<{{token}}>x</p>", "{{token}}"),
            ("value_in_a_loop_that_ends_inside_a_tag", "{{#each items}}{{token}}<img alt={{/each}}>", "{{token}}"),
            (
                "value_in_a_loop_whose_condition_ends_in_a_style",
                "{{#each items}}{{#if v}}x{{else}}{{token}}<style>{{/if}}{{/each}}",
                "{{token}}",
            ),
            ("value_after_a_with_that_ends_inside_a_tag", "{{#with u}}<img alt={{/with}}{{token}}>", "{{token}}"),
            ("value_after_an_escaped_tag_that_names_endraw", '<img alt=\\{{ ="endraw}}{{token}}>', "{{token}}"),
            (
                "value_in_a_style_only_the_else_branch_opens",
                '{{#if c}}<style>a<b alt="{{else}}<style>{{token}}{{/if}}',
                "{{token}}",
            ),
            (
                "value_in_a_comment_only_the_else_branch_opens",
                '{{#if c}}<!--a<b alt="{{else}}<!--{{token}}{{/if}}',
                "{{token}}",
            ),
            (
                "value_after_branches_that_end_a_comment_differently",
                "<!--{{#if c}}-{{else}}x{{/if}}->{{token}}",
                "{{token}}",
            ),
            (
                "value_after_branches_that_end_a_style_differently",
                "<style>{{#if c}}</sty{{else}}x{{/if}}le><p>{{token}}</p>",
                "{{token}}",
            ),
            (
                "value_in_a_style_after_a_loop_kept_as_written",
                "{{#each items}}<style>a<b alt={{/each}}<style>{{token}}",
                "{{token}}",
            ),
            ("value_after_a_no_break_space_in_an_unquoted_value", '<img alt=x\u00a0title="{{token}}">', "{{token}}"),
            ("value_in_a_script_opened_around_a_comment", "<{{!-- c --}}script>var a = {{x}};</script>", "{{x}}"),
            ("raw_value_in_an_attribute", '<a href="{{{token}}}">x</a>', "{{{token}}}"),
            (
                "event_handler_hidden_by_an_angle_bracket",
                '<a title="a>b" onclick="{{first_name}}">x</a>',
                "{{first_name}}",
            ),
            (
                "event_handler_hidden_by_a_tag_like_value",
                '<a title="<%%>" onclick="{{first_name}}">x</a>',
                "{{first_name}}",
            ),
            (
                "value_in_an_event_handler_that_looks_like_an_attribute",
                "<a onclick=\"const x='{{token}}'; go(x)\">x</a>",
                "{{token}}",
            ),
            ("value_after_an_unclosed_script", "<script>var u = {{x}};", "{{x}}"),
            ("value_after_an_unclosed_comment", "<!-- <p>{{x}}</p>", "{{x}}"),
            (
                "value_after_a_head_closing_tag_in_a_css_string",
                '<head><style>p{content:"</head>"}{{name}}</style></head>',
                "{{name}}",
            ),
            ("value_in_a_tag_that_never_closes", "<a href=/{{id}} <b>x", "{{id}}"),
            ("value_after_a_double_escaped_script", "<script><!--<script></script>{{x}}</script>", "{{x}}"),
            (
                "value_after_branches_that_end_in_different_places",
                '<a href="{{#if x}}https://example.com">{{t}}</a>{{/if}} {{after}}',
                "{{after}}",
            ),
            ("liquid_size_property", "<p>{{size}}</p>", "{{size}}"),
            ("liquid_first_property", "<p>{{items.first}}</p>", "{{items.first}}"),
            ("a_body_tag", "<p><%body%></p>", "<%body%>"),
            (
                "unsubscribe_link_in_an_event_handler",
                '<a onclick="<%asm_group_unsubscribe_url%>">x</a>',
                "<%asm_group_unsubscribe_url%>",
            ),
            (
                "unsubscribe_link_in_a_quoted_attribute",
                '<a title="<%asm_group_unsubscribe_url%>">x</a>',
                "<%asm_group_unsubscribe_url%>",
            ),
            (
                "unsubscribe_link_in_a_comment",
                "<!-- <%asm_group_unsubscribe_url%> --><p>x</p>",
                "<%asm_group_unsubscribe_url%>",
            ),
            ("unsubscribe_in_a_loop", "{{#each unsubscribe}}x{{/each}}", "{{#each unsubscribe}}"),
            ("unsubscribe_in_a_with", "{{#with this.unsubscribe}}x{{/with}}", "{{#with this.unsubscribe}}"),
            ("unsubscribe_in_a_condition", "{{#if unsubscribe}}x{{/if}}", "{{#if unsubscribe}}"),
        ]
    )
    def test_a_tag_without_a_faithful_liquid_form_stays_as_written(self, _name: str, html: str, kept: str) -> None:
        converted = convert_version({"html_content": html + "<p>{{name}}</p>", "generate_plain_content": False})

        assert kept in " ".join(converted.notes)
        assert (liquid_literal(kept) if kept.startswith("{{") else kept) in converted.html

    @parameterized.expand(
        [
            ("if", "{{#if x}}a{ {{~/if}}"),
            ("else", "{{#if x}}a{{else}}b{ {{~/if}}"),
            ("each", "{{#each xs}}a{ {{~/each}}"),
            ("with", "{{#with x}}a{ {{~/with}}"),
            ("kept_block", "{{#or a b}}a{ {{~/or}}"),
        ]
    )
    def test_a_brace_before_a_block_tag_never_joins_it(self, _name: str, html: str) -> None:
        converted = convert_version({"html_content": html, "generate_plain_content": False})

        assert "{{%" not in converted.html

    def test_a_loop_variable_never_hides_a_value_assigned_for_a_comparison(self) -> None:
        html = "{{#each items as |text1|}}{{#equals text1.code 5}}Y{{/equals}}{{/each}}"

        converted = convert_version({"html_content": html, "generate_plain_content": False})

        assert converted.html.endswith(
            '{% assign text1 = item.code | join: "," | append: "" %}{% if text1 == "5" %}Y{% endif %}{% endfor %}{% endif %}'
        )

    def test_the_rest_of_the_template_converts_around_a_tag_kept_as_written(self) -> None:
        converted = convert_version(
            {"html_content": "<p>Hi {{first_name}}</p><p>{{helper a}}</p>", "generate_plain_content": False}
        )

        assert (
            converted.html == '<p>Hi {{ variables.first_name | join: "," }}</p><p>{% raw %}{{helper a}}{% endraw %}</p>'
        )

    @parameterized.expand([("values", "{{this}}" * 20_000), ("conditions", "{{#if this}}{{/if}}" * 200)])
    def test_paths_that_grow_with_nesting_stop_before_the_output_gets_too_large(self, _name: str, body: str) -> None:
        html = "".join(f"{{{{#with {'a' * 1200}}}}}" for _ in range(40)) + body + "{{/with}}" * 40

        tracemalloc.start()
        try:
            converted = convert_version({"html_content": html, "generate_plain_content": False})
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert peak_bytes < 30_000_000
        assert "too large" in " ".join(converted.notes)
        assert "variables." not in converted.html

    @parameterized.expand([("unclosed_block", "{{#if a}}unclosed"), ("stray_close", "{{/if}}{{name}}")])
    def test_a_template_that_isnt_valid_handlebars_stays_as_text(self, _name: str, html: str) -> None:
        converted = convert_version({"html_content": html})

        assert "this template's tags" in " ".join(converted.notes)
        assert "variables." not in converted.html + converted.text

    @parameterized.expand(
        [
            ("value", "<p>Hi {{ name }}</p>", '{{ variables.name | join: "," }}'),
            ("unsubscribe_link", "<p>{{unsubscribe}}</p>", "{{ unsubscribe_url }}"),
            ("unsubscribe_link_from_a_loop", "{{#each a}}<p>{{../unsubscribe}}</p>{{/each}}", "{{ unsubscribe_url }}"),
            (
                "unsubscribe_link_from_the_root",
                "{{#each a}}<p>{{@root.unsubscribe}}</p>{{/each}}",
                "{{ unsubscribe_url }}",
            ),
            ("unsubscribe_link_of_this", "<p>{{this.unsubscribe}}</p>", "{{ unsubscribe_url }}"),
            ("unsubscribe_link_with_a_default", '<p>{{insert unsubscribe "default=x"}}</p>', "{{ unsubscribe_url }}"),
            ("unescaped_unsubscribe_link", '<a href="{{{unsubscribe}}}">Leave</a>', '<a href="{{ unsubscribe_url }}">'),
            (
                "unsubscribe_link_tag",
                "<p><%asm_group_unsubscribe_url%></p>",
                '<p><a href="{{ unsubscribe_url }}">Unsubscribe From This List</a></p>',
            ),
            (
                "value_after_a_loop_that_closes_its_own_tags",
                '<h1>x</h1>{{#each xs}}<p>{{this}}</p>{{/each}}<a href="{{after}}">y</a>',
                '<a href="{{ variables.after | join: &quot;,&quot; }}">',
            ),
            (
                "global_unsubscribe_tag",
                '<a href="<%asm_global_unsubscribe_raw_url%>">x</a>',
                '<a href="{{ unsubscribe_url }}">',
            ),
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

    def test_plain_text_never_runs_entity_spelled_liquid_around_a_tag_kept_as_text(self) -> None:
        html = "Hi &#123;&#123; \\{{a}} &#123;% echo person.properties.secret %&#125; &#123;% raw %&#125; }}"

        text = convert_version({"html_content": html}).text

        assert "{% raw %}{% echo person.properties.secret %}{% endraw %}" in text
        assert text.count("{% echo") == 1

    def test_an_attribute_full_of_angle_brackets_is_checked_quickly(self) -> None:
        started = time.monotonic()
        convert_version({"html_content": '<a title="' + ">" * 64_000, "generate_plain_content": False})

        assert time.monotonic() - started < 1

    def test_plain_text_keeps_a_stray_brace_from_joining_a_tag(self) -> None:
        converted = convert_version({"html_content": "<p>{<b>{{name}}</b></p>"})

        assert "{{{" not in converted.text
        assert converted.text.endswith('{{ variables.name | join: "," }}')

    @parameterized.expand(
        [
            (
                "a_value",
                "Dear -first_name-,",
                'Dear {% if variables.first_name == nil %}-first_name-{% else %}{{ variables.first_name | join: "," }}'
                "{% endif %},",
            ),
            (
                "a_link_url",
                "<a href='-reset_link-'>Reset</a>",
                "<a href='{% if variables.reset_link == nil %}-reset_link-{% else %}{{ variables.reset_link | "
                'join: "," }}{% endif %}\'>Reset</a>',
            ),
            (
                "part_of_a_url",
                '<img src="/i/-hero-.png">',
                '<img src="/i/{% if variables.hero == nil %}-hero-{% else %}{{ variables.hero | join: &quot;,&quot; }}{% endif %}'
                '.png">',
            ),
            ("hyphenated_words", "a well-known-fact --x-- -a-b-", "a well-known-fact --x-- -a-b-"),
            ("a_body_tag", "<p>x{</p>{<%body%>", '<p>x{</p>{{ "{" }}{{ variables.body | raw }}'),
            (
                "an_unsubscribe_url",
                '<a href="<%asm_preferences_raw_url%>">Leave</a>',
                '<a href="{{ unsubscribe_url }}">Leave</a>',
            ),
            (
                "an_escaped_unsubscribe_link",
                "&lt;%asm_group_unsubscribe_url%&gt;",
                '<a href="{{ unsubscribe_url }}">Unsubscribe From This List</a>',
            ),
            (
                "a_value_after_the_body_html",
                '<%body%><img alt="-x-">',
                '{{ variables.body | raw }}<img alt="{% if variables.x == nil %}-x-{% else %}{{ variables.x | '
                'join: &quot;,&quot; | escape | replace: &quot;=&quot;, &quot;&amp;#x3D;&quot; | replace: &quot;`&quot;, &quot;&amp;#x60;&quot; | raw }}{% endif %}">',
            ),
        ]
    )
    def test_a_legacy_template_converts_what_the_app_fills(self, _name: str, html: str, expected: str) -> None:
        converted = convert_version(
            {"subject": "<%subject%>", "html_content": html, "plain_content": "Hi <%body%>"}, generation="legacy"
        )

        assert converted.html == expected
        assert converted.subject == '{{ variables.subject | join: "," }}'
        assert not any("can't convert" in note for note in converted.notes)
        assert any("another style" in note for note in converted.notes)
        assert "subject" in " ".join(converted.send_notes)

    @parameterized.expand(
        [
            ("an_event_handler", '<a onclick="-x-">t</a>'),
            ("a_style_block", "<style>-x- <%body%></style>"),
            ("an_unclosed_title", "<title><%body%>"),
            ("after_a_comment_in_a_script", "<script><!--1</script><%body%>"),
            ("a_comment", "<!-- <%body%>"),
            ("an_attribute", '<a title="<%body%>">t</a>'),
            ("liquid", "<title>{{ person.properties.secret }}</title><!-- {% x %} -->"),
        ]
    )
    def test_a_legacy_template_keeps_what_is_not_safe_there_as_text(self, _name: str, html: str) -> None:
        converted = convert_version(
            {"subject": "", "html_content": html, "generate_plain_content": False}, generation="legacy"
        )

        assert "variables." not in converted.html
        assert "{{ " not in converted.html.replace("{% raw %}{{ ", "")

    @parameterized.expand(
        [
            ("legacy", "legacy", "<a href=<%asm_group_unsubscribe_raw_url%>>Leave</a>"),
            ("dynamic", "dynamic", "<a href={{{unsubscribe}}}#top>Leave</a>"),
            ("malformed", "dynamic", '{{#if a}}<a href="{{{unsubscribe}}}">Leave</a>'),
            (
                "next_to_one_that_converts",
                "legacy",
                "<i><%asm_preferences_raw_url%></i><a href=<%asm_group_unsubscribe_raw_url%>>Leave</a>",
            ),
            (
                "after_something_like_a_comment",
                "legacy",
                '<a title="a <!-- b">x</a><a href=<%asm_group_unsubscribe_raw_url%>>Leave</a>',
            ),
            ("url_encoded_braces", "dynamic", '<a href="%7B%7B%7Bunsubscribe%7D%7D%7D">Leave</a>'),
            ("url_encoded", "legacy", '<a href="%3C%25asm_group_unsubscribe_raw_url%25%3E">Leave</a>'),
            ("handlebars_in_a_legacy_template", "legacy", '<a href="{{{unsubscribe}}}">Leave</a>'),
            ("another_tag", "legacy", '<a href="<%unsubscribe%>">Leave</a>'),
            ("malformed_tag", "dynamic", '{{#if a}}<a href="<%asm_group_unsubscribe_raw_url%>">Leave</a>'),
        ]
    )
    def test_a_lost_unsubscribe_link_is_said_clearly(self, _name: str, generation: str, html: str) -> None:
        converted = convert_version({"html_content": html}, generation=generation)

        assert "unsubscribe link didn't convert" in " ".join(converted.notes)

    @parameterized.expand([("legacy",), ("dynamic",)])
    def test_a_lost_unsubscribe_link_in_a_plain_text_only_version_is_said_clearly(self, generation: str) -> None:
        converted = convert_version(
            {"plain_content": "Leave: %3C%25asm_group_unsubscribe_raw_url%25%3E"}, generation=generation
        )

        assert "unsubscribe link didn't convert" in " ".join(converted.notes)

    @parameterized.expand(
        [
            ("a_value_the_app_passes", "legacy", '<a href="-unsubscribe_link-">Leave</a>'),
            ("a_dynamic_value", "dynamic", '<a href="{{unsubscribe_link}}">Leave</a>'),
            ("a_nested_dynamic_value", "dynamic", '<a href="{{links.unsubscribe}}">Leave</a>'),
            ("a_markdown_link", "dynamic", "<p>[Unsubscribe](https://example.com/u)</p>"),
        ]
    )
    def test_a_working_unsubscribe_link_is_not_reported_lost(self, _name: str, generation: str, html: str) -> None:
        converted = convert_version({"html_content": html}, generation=generation)

        assert not any("link didn't convert" in note for note in converted.notes)

    def test_plain_text_keeps_the_url_of_a_link_whose_conditions_are_whole(self) -> None:
        converted = convert_version(
            {"html_content": '<a href="https://example.com/a">Hi -name-</a>'}, generation="legacy"
        )

        assert converted.text.endswith("{% endif %} (https://example.com/a)")
        converted = convert_version({"html_content": "<a href='-link-'>Go</a>"}, generation="legacy")
        assert converted.text.startswith("Go ({% if variables.link == nil %}-link-{% else %}")

    @parameterized.expand(
        [
            ("triple", "{{{first_name}}}"),
            ("ampersand", "{{& first_name}}"),
            ("insert", '{{{insert first_name "default=x"}}}'),
            ("in_a_loop", "{{#each tags}}{{{this}}}{{/each}}"),
        ]
    )
    def test_a_contact_field_never_prints_html(self, _name: str, html: str) -> None:
        unescaped = re.compile(r"(?:join: \",\"|default: \"x\") \| raw \}\}")
        assert unescaped.search(convert_version({"html_content": html}).html)
        converted = convert_version({"html_content": html}, contact_fields=True)

        assert "person.properties." in converted.html
        assert not unescaped.search(converted.html)

    @parameterized.expand(
        [
            ("single_send", True, "person.properties"),
            ("dynamic", False, "variables"),
        ]
    )
    def test_contact_fields_read_the_person_and_a_send_reads_its_variables(
        self, _name: str, contact_fields: bool, root: str
    ) -> None:
        converted = convert_version(
            {
                "subject": "Hi {{first_name}}",
                "html_content": "<p>{{#if Plan}}{{Plan}}{{/if}} {{#if Sender_Name}}{{Sender_Name}}{{/if}} {{{unsubscribe}}}</p>",
                "generate_plain_content": False,
                "plain_content": "{{Plan}}",
            },
            contact_fields=contact_fields,
        )

        assert converted.subject == f'Hi {{{{ {root}.first_name | join: "," }}}}'
        assert f'{{{{ {root}.Plan | join: "," }}}}' in converted.html
        assert f"{{% if {root}.Plan" in converted.html
        assert "{% if variables.Sender_Name" in converted.html
        assert "{{ variables.Sender_Name" in converted.html
        assert "{{ unsubscribe_url }}" in converted.html
        assert converted.text == f'{{{{ {root}.Plan | join: "," }}}}'
        assert any("print the person's property" in note for note in converted.send_notes) == contact_fields

    def test_plain_text_is_built_from_the_html_when_sendgrid_would_build_it(self) -> None:
        html = (
            "<html><head><style>p{color:red}</style></head><body><p>Hi {{ variables.n | raw }}</p>"
            '{% if variables.a > 1 %}<a href="{{ unsubscribe_url }}">Leave</a>{% endif %}<br>Tom &amp; Ann<br>'
            "&#123;&#123; person.properties.secret &#125;&#125; <b>{</b>{ x }}</body></html>"
        )

        assert plain_text_from_html(html) == (
            "Hi {{ variables.n | strip_html }}\n{% if variables.a > 1 %}Leave ({{ unsubscribe_url }}){% endif %}\nTom & Ann\n"
            "{% raw %}{{ person.properties.secret }}{% endraw %} {% raw %}{{ x }}{% endraw %}"
        )

    @parameterized.expand(
        [
            (
                "a_value_after_raw_html",
                "<p>{{{intro}}}</p><p>Hi {{name}}</p>",
                '{{ variables.intro | join: "," | strip_html }}\nHi {{ variables.name | join: "," }}',
            ),
            (
                "values_in_the_title_and_an_outlook_comment",
                "<head><title>Order {{id}}</title></head><body><!--[if mso]>{{first_name}}<![endif]--><p>Hi</p></body>",
                "Hi",
            ),
            (
                "a_condition_that_opens_inside_an_attribute",
                '<p class="{{#if a}}x">A{{else}}y">B{{/if}}</p>',
                '{% if variables.a != nil and variables.a != false and variables.a != 0 and variables.a.length != 0 or variables.a != empty %}A{% else %}y">B{% endif %}',
            ),
            (
                "a_condition_inside_a_link",
                '<p>{{#if allow}}<a href="{{token}}">Reset{{/if}}</a></p>',
                "{% if variables.allow != nil and variables.allow != false and variables.allow != 0 and variables.allow.length != 0 or variables.allow != empty %}Reset{% endif %}",
            ),
            (
                "a_condition_that_closes_after_the_title",
                "<head><title>{{#if a}}Sale</title></head><body>x{{/if}}",
                "{% if variables.a != nil and variables.a != false and variables.a != 0 and variables.a.length != 0 or variables.a != empty %}x{% endif %}",
            ),
        ]
    )
    def test_plain_text_built_from_converted_html(self, _name: str, html: str, text: str) -> None:
        assert convert_version({"html_content": html}).text == text

    def test_plain_text_keeps_each_test_of_an_and_whole(self) -> None:
        html = '<a title="{{#and a b}}">{{token}}<a title="{{/and}}">x</a>'

        converted = convert_version({"html_content": html})

        assert "{% assign truthy1 = true %}" in converted.text

    def test_plain_text_keeps_how_a_loop_reads_its_value(self) -> None:
        html = '<a title="{{#each items}}">{{#unless restricted}}{{../token}}{{/unless}}<a title="{{/each}}">x</a>'

        converted = convert_version({"html_content": html})

        assert '{% assign shape1 = "list" %}' in converted.text

    def test_plain_text_prints_values_without_html_escaping(self) -> None:
        converted = convert_version({"html_content": '<p>{{name}} <a href="<%asm_preferences_raw_url%>">Go</a></p>'})

        assert converted.text == '{{ variables.name | join: "," }} Go ({{ unsubscribe_url }})'

    @parameterized.expand(
        [
            ("escaped_tag", '<a \\{{x a="&}}{{name}}">'),
            ("unsupported_tag", '<p title="{{x "a="b &amp;}}">'),
        ]
    )
    def test_quotes_a_kept_tag_prints_stay_quotes(self, _name: str, html: str) -> None:
        converted = convert_version({"html_content": html}).html

        assert 'a="' in converted and "a=&quot;" not in converted

    @parameterized.expand(
        [
            (
                "with_a_brace_in_a_default",
                '{{{body}}}<a href="{{insert url "default={x"}}">Go</a>',
                'Go ({{ variables.url | default: "{x" | join: "," }})',
            ),
            ("after_raw_html", '{{{body}}}<a href="{{url}}">Go</a>', 'Go ({{ variables.url | join: "," }})'),
            (
                "next_to_a_tag_kept_as_text",
                '<a href="https://example.com/{{a%20b}}?n={{n}}">Go</a>',
                'Go (https://example.com/{{ "{{" }}a%20b}}?n={{ variables.n | join: "," }})',
            ),
        ]
    )
    def test_plain_text_reads_the_liquid_of_a_link(self, _name: str, html: str, expected: str) -> None:
        converted = convert_version({"html_content": html})

        assert expected in converted.text

    def test_an_unsubscribe_tag_kept_as_text_stays_whole_in_the_plain_part(self) -> None:
        converted = convert_version(
            {"html_content": '{{#if a}}<p><a href="<%asm_group_unsubscribe_raw_url%>">Leave</a></p>'}
        )

        assert converted.text == "{% raw %}{{#if a}}{% endraw %}Leave (<%asm_group_unsubscribe_raw_url%>)"

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
