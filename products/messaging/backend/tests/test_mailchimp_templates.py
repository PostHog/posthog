from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports.mailchimp_templates import convert_email, convert_text

ESCAPED_FNAME = "{{ person.properties.first_name | escape | raw }}"


class TestMailchimpMergeTags(SimpleTestCase):
    @parameterized.expand(
        [
            ("value_in_text", "<p>Hi *|FNAME|*</p>", f"<p>Hi {ESCAPED_FNAME}</p>", ()),
            ("email_reads_the_email_property", "*|EMAIL|*", "{{ person.properties.email | escape | raw }}", ()),
            ("lname_reads_the_last_name_property", "*|lname|*", "{{ person.properties.last_name | escape | raw }}", ()),
            ("html_modifier_prints_raw", "<div>*|HTML:BIO|*</div>", "<div>{{ person.properties.BIO | raw }}</div>", ()),
            ("value_in_quoted_attribute", '<a title="*|FNAME|*">x</a>', f'<a title="{ESCAPED_FNAME}">x</a>', ()),
            (
                "value_in_style_stays",
                '<p style="color: *|COLOR|*">x</p>',
                '<p style="color: *|COLOR|*">x</p>',
                ("*|COLOR|*",),
            ),
            (
                "raw_value_in_attribute_stays",
                '<a title="*|HTML:X|*">x</a>',
                '<a title="*|HTML:X|*">x</a>',
                ("*|HTML:X|*",),
            ),
            (
                "value_in_script_stays",
                "<script>var a='*|FNAME|*'</script>",
                "<script>var a='*|FNAME|*'</script>",
                ("*|FNAME|*",),
            ),
            ("unsubscribe_link", '<a href="*|UNSUB|*">x</a>', '<a href="{{ unsubscribe_url }}">x</a>', ()),
            (
                "mailchimp_only_tag_stays",
                '<a href="*|ARCHIVE|*">x</a>',
                '<a href="*|ARCHIVE|*">x</a>',
                ("*|ARCHIVE|*",),
            ),
            ("current_year", "&copy; *|CURRENT_YEAR|*", '&copy; {{ "now" | date: "%Y" }}', ()),
            ("date_format", "*|DATE:d/m/Y|*", '{{ "now" | date: "%d/%m/%Y" }}', ()),
            ("date_letter_without_a_match_stays", "*|DATE:jS|*", "*|DATE:jS|*", ("*|DATE:jS|*",)),
            ("liquid_in_source_stays_text", "{{ x }} {% raw %}", '{{ "{{" }} x }} {{ "{%" }} raw %}', ()),
            (
                "balanced_condition",
                "*|IF:FNAME|*Hi *|FNAME|**|ELSE:|*Hi*|END:IF|*",
                '{% if person.properties.first_name and person.properties.first_name != "" %}Hi '
                + ESCAPED_FNAME
                + "{% else %}Hi{% endif %}",
                (),
            ),
            (
                "comparison_and_elseif",
                "*|IF:PLAN=pro|*A*|ELSEIF:PLAN!=free|*B*|END:IF|*",
                '{% if person.properties.PLAN == "pro" %}A{% elsif person.properties.PLAN != "free" %}B{% endif %}',
                (),
            ),
            (
                "ifnot",
                "*|IFNOT:FNAME|*friend*|END:IF|*",
                '{% if person.properties.first_name == nil or person.properties.first_name == "" %}friend{% endif %}',
                (),
            ),
            (
                "unclosed_condition_stays_but_values_convert",
                "*|IF:FNAME|*Hi *|FNAME|*",
                f"*|IF:FNAME|*Hi {ESCAPED_FNAME}",
                ("*|IF:FNAME|*",),
            ),
            (
                "entity_in_condition_leaves_every_condition",
                "*|IF:CITY=S&atilde;o Paulo|*Ol&aacute;*|END:IF|*",
                "*|IF:CITY=S&atilde;o Paulo|*Ol&aacute;*|END:IF|*",
                ("*|IF:CITY=S&atilde;o Paulo|*", "*|END:IF|*"),
            ),
            (
                "number_comparison_stays",
                "*|IF:AGE=21|*A*|END:IF|*",
                "*|IF:AGE=21|*A*|END:IF|*",
                ("*|IF:AGE=21|*", "*|END:IF|*"),
            ),
            (
                "branches_ending_in_different_html_leave_later_values",
                '*|IF:VIP|*<a title="*|ELSE:|*<a title=*|END:IF|**|FNAME|*>',
                '{% if person.properties.VIP and person.properties.VIP != "" %}<a title="{% else %}<a title={% endif %}'
                "*|FNAME|*>",
                ("*|FNAME|*",),
            ),
            (
                "greater_than_comparison_stays",
                "*|IF:AGE>20|*A*|END:IF|*",
                "*|IF:AGE>20|*A*|END:IF|*",
                ("*|IF:AGE>20|*", "*|END:IF|*"),
            ),
        ]
    )
    def test_converts_html(self, _name: str, source: str, expected: str, unsupported: tuple[str, ...]) -> None:
        converted = convert_text(source, is_html=True)

        assert converted.text == expected
        assert converted.unsupported == unsupported

    def test_output_too_large_to_send_keeps_tags_as_written(self) -> None:
        converted = convert_text("*|FNAME|*" * 110_000, is_html=True)

        assert converted.too_large
        assert len(converted.text) <= 5_000_000
        assert "{{ person" not in converted.text

    def test_subject_prints_values_without_html_escaping(self) -> None:
        assert convert_text("*|FNAME|*, hi", is_html=False).text == "{{ person.properties.first_name }}, hi"

    def test_fixed_tags_go_in_as_escaped_text(self) -> None:
        converted = convert_text("<p>*|LIST:COMPANY|*</p>", is_html=True, fixed={"LIST:COMPANY": "A & B {{ evil }}"})

        assert converted.text == '<p>A &amp; B {{ "{{" }} evil }}</p>'

    def test_email_notes_name_what_to_check(self) -> None:
        converted = convert_email(
            "", "*|FNAME|* *|lname|* *|EMAIL|* *|ARCHIVE|* *|IF:X|*a*|END:IF|* *|UPDATE_PROFILE|*", None
        )

        assert converted.notes == (
            "PostHog can't convert *|ARCHIVE|*, so it stays as written. Replace it with Liquid or remove it.",
            "PostHog converted the IF conditions to Liquid. Send yourself a test to check each one.",
            "*|UPDATE_PROFILE|* now opens the PostHog preferences page.",
            "This email has no subject in Mailchimp. Add one here.",
        )
        assert converted.send_notes == (
            "Set these person properties on your people or change the template: X, first_name (FNAME in "
            "Mailchimp), last_name (LNAME in Mailchimp).",
        )

    def test_a_clean_template_has_no_notes(self) -> None:
        converted = convert_email("", "<p>Hi *|EMAIL|*</p>", None, expects_subject=False)

        assert (converted.notes, converted.send_notes) == ((), ())

    @parameterized.expand(
        [
            ("known_preview_text_shows", {"MC_PREVIEW_TEXT": "New this week"}, "{% if true %}New this week{% endif %}"),
            ("empty_preview_text_hides", {"MC_PREVIEW_TEXT": ""}, "{% if false %}{% endif %}"),
            ("unknown_preview_text_stays", {}, "*|IF:MC_PREVIEW_TEXT|**|MC_PREVIEW_TEXT|**|END:IF|*"),
            (
                "preview_text_with_tags_shows_as_written",
                {"MC_PREVIEW_TEXT": None},
                "{% if true %}*|MC_PREVIEW_TEXT|*{% endif %}",
            ),
        ]
    )
    def test_a_condition_on_a_fixed_tag_is_decided_at_import(
        self, _name: str, fixed: dict[str, str | None], expected: str
    ) -> None:
        converted = convert_text("*|IF:MC_PREVIEW_TEXT|**|MC_PREVIEW_TEXT|**|END:IF|*", is_html=True, fixed=fixed)

        assert converted.text == expected
        assert converted.merge_fields == ()
