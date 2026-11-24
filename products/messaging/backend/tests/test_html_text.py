import tracemalloc

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.services.html_text import text_from_html


class TestTextFromHtml(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "blocks_become_lines",
                "<h1>Reset</h1><p>Hi Jane,</p><p>Use the link.</p>",
                "Reset\n\nHi Jane,\n\nUse the link.",
            ),
            ("line_breaks_stay", "<p>Line one<br>Line two</p>", "Line one\nLine two"),
            ("hidden_parts_are_dropped", "<style>p{color:red}</style><script>x()</script><p>Hi</p>", "Hi"),
            ("entities_are_decoded", "<p>Tom &amp; Jerry&nbsp;&lt;3</p>", "Tom & Jerry <3"),
            ("source_whitespace_collapses", "<p>Hi\n      Jane</p>\n\n\n<p>Bye</p>", "Hi Jane\n\nBye"),
            ("list_items_are_lines", "<ul><li>One</li><li>Two</li></ul>", "One\nTwo"),
            ("text_after_a_line_block_starts_a_new_line", "<div>Order 123</div>shipped", "Order 123\nshipped"),
        ]
    )
    def test_derives_readable_text(self, _name, html, expected):
        assert text_from_html(html) == expected

    @parameterized.expand(
        [
            (
                "marketing_send",
                '<a href="{{unsubscribe_url}}">Unsubscribe</a>',
                True,
                "Unsubscribe ({{unsubscribe_url}})",
            ),
            (
                "marketing_send_with_nbsp",
                '<a href="{{\u00a0unsubscribe_url\u00a0}}">Unsubscribe</a>',
                True,
                "Unsubscribe ({{ unsubscribe_url }})",
            ),
            (
                "marketing_send_with_bom",
                '<a href="{{\ufeffunsubscribe_url }}">Unsubscribe</a>',
                True,
                "Unsubscribe ({{\ufeffunsubscribe_url }})",
            ),
            (
                "marketing_send_with_surrounding_bom",
                '<a href="\ufeff{{unsubscribe_url}}\ufeff">Unsubscribe</a>',
                True,
                "Unsubscribe",
            ),
            (
                "marketing_send_with_nel",
                '<a href="{{\u0085unsubscribe_url }}">Unsubscribe</a>',
                True,
                "Unsubscribe",
            ),
            (
                "marketing_send_with_surrounding_nel",
                '<a href="\u0085{{unsubscribe_url}}">Unsubscribe</a>',
                True,
                "Unsubscribe",
            ),
            (
                "marketing_send_with_fragment",
                '<a href="{{ unsubscribe_url }}#preferences">Unsubscribe</a>',
                True,
                "Unsubscribe ({{ unsubscribe_url }}#preferences)",
            ),
            (
                "marketing_send_with_query_and_fragment",
                '<a href="{{ unsubscribe_url }}?utm_source=email#preferences">Unsubscribe</a>',
                True,
                "Unsubscribe ({{ unsubscribe_url }}?utm_source=email#preferences)",
            ),
            (
                "marketing_send_with_newline_in_query",
                '<a href="{{ unsubscribe_url }}?utm_source=email\n&utm_medium=message">Unsubscribe</a>',
                True,
                "Unsubscribe ({{ unsubscribe_url }}?utm_source=email&utm_medium=message)",
            ),
            (
                "marketing_send_with_newline_before_query",
                '<a href="{{ unsubscribe_url }}\n?utm_source=email">Unsubscribe</a>',
                True,
                "Unsubscribe ({{ unsubscribe_url }}?utm_source=email)",
            ),
            (
                "marketing_send_with_newline_in_fragment",
                '<a href="{{ unsubscribe_url }}#pref\nerences">Unsubscribe</a>',
                True,
                "Unsubscribe ({{ unsubscribe_url }}#preferences)",
            ),
            (
                "marketing_send_with_space_before_fragment",
                '<a href="{{ unsubscribe_url }} #preferences">Unsubscribe</a>',
                True,
                "Unsubscribe",
            ),
            (
                "marketing_send_with_extra_path_segment",
                '<a href="{{ unsubscribe_url }}extra">Unsubscribe</a>',
                True,
                "Unsubscribe",
            ),
            ("transactional_send", '<a href="{{unsubscribe_url}}">Unsubscribe</a>', False, "Unsubscribe"),
        ]
    )
    def test_keeps_the_unsubscribe_placeholder_link_only_when_asked(self, _name, html, keep, expected):
        assert text_from_html(html, keep_unsubscribe_link=keep) == expected

    @parameterized.expand(
        [
            (
                "links_that_show_their_address",
                '<a href="https://example.com">' * 5000 + "https://example.com" + "</a>" * 5000,
                "https://example.com",
            ),
            (
                "links_with_a_label",
                '<a href="https://example.com">' * 5000 + "Go" + "</a>" * 5000,
                "Go" + " (https://example.com)" * 5000,
            ),
            (
                "link_inside_a_link",
                '<a href="https://example.com/a">Outer <a href="https://example.com/b">https://example.com/b</a></a>',
                "Outer https://example.com/b (https://example.com/a)",
            ),
            (
                "address_split_over_elements",
                '<a href="https://example.com/ab">https://example.com/<b>ab</b></a>',
                "https://example.com/ab",
            ),
        ]
    )
    def test_deeply_nested_html_still_gives_its_text(self, _name, html, expected):
        assert text_from_html(html) == expected

    @parameterized.expand(
        [
            ("line_breaks", "<br>" * 131072 + "Hi", "Hi"),
            ("unclosed_nesting", "<div><p>" * 65536 + "Hi", "Hi"),
            ("closed_nesting", "<div>" * 50000 + "Hi" + "</div>" * 50000, "Hi"),
        ]
    )
    def test_half_a_mebibyte_of_markup_converts_in_bounded_memory(self, _name, html, expected):
        tracemalloc.start()
        try:
            text = text_from_html(html)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert text == expected
        assert peak < 24 * 1024 * 1024

    @pytest.mark.timeout(30, func_only=True)
    def test_closing_tags_without_an_open_match_convert_in_linear_time(self):
        html = "<div>" * 43690 + "Hi" + "</span>" * 43690

        assert text_from_html(html) == "Hi"
