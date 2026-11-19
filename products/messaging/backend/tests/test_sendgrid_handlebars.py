from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports.sendgrid_handlebars import (
    _Block,
    _Call,
    _Liquid,
    _Literal,
    _Malformed,
    _Output,
    _parse_expression,
    _parse_nodes,
    _Path,
    _Text,
    _tokenize,
    _Unconvertible,
)


def _parse(source: str) -> tuple[object, ...]:
    return _parse_nodes(_tokenize(source, is_html=False))


class TestSendGridHandlebars(SimpleTestCase):
    def test_one_backslash_keeps_a_tag_as_text_and_two_print_one_and_run_it(self) -> None:
        escaped, doubled = _parse("\\{{n}}"), _parse("\\\\{{n}}")

        assert escaped == (_Text(text=""), _Liquid(liquid="{% raw %}{{n}}{% endraw %}"))
        assert doubled[0] == _Text(text="\\")
        assert isinstance(doubled[1], _Output) and doubled[1].body == "n"

    def test_an_else_if_chain_shares_the_closing_tag_of_the_block_that_opened_it(self) -> None:
        (block,) = _parse("{{#if a}}A{{else if b}}B{{/if}}")

        assert isinstance(block, _Block)
        (chained,) = block.inverse
        assert isinstance(chained, _Block) and chained.chained
        assert chained.source_open == "{{else if b}}"
        assert block.source_close == chained.source_close == "{{/if}}"

    def test_an_expression_reads_parameters_hash_arguments_and_block_names(self) -> None:
        expression = _parse_expression('each (lookup orders "open") limit=3 as |order i|')

        assert expression.name == "each"
        assert expression.params == (
            _Call(name="lookup", params=(_Path(source="orders"), _Literal(liquid='"open"', text="open"))),
        )
        assert set(expression.hash_args) == {"limit"}
        assert expression.block_params == ("order", "i")

    def test_three_backslashes_print_two_and_run_the_tag_as_handlebars_does(self) -> None:
        nodes = _parse("\\\\\\{{n}}")

        assert nodes[0] == _Text(text="\\\\")
        assert isinstance(nodes[1], _Output) and nodes[1].body == "n"

    @parameterized.expand(
        [
            ("trimmed_opening", "{{~!-- hidden }} {{secret}} --}}x", "x"),
            ("trimmed_closing", "{{!-- note --~}}  x", "x"),
        ]
    )
    def test_a_long_comment_with_whitespace_control_hides_everything_inside(
        self, _name: str, source: str, text: str
    ) -> None:
        assert [node for node in _parse(source) if not isinstance(node, _Text) or node.text] == [_Text(text=text)]

    def test_any_whitespace_after_else_chains_the_next_condition(self) -> None:
        (block,) = _parse("{{#if a}}A{{else\tif b}}B{{/if}}")

        assert isinstance(block, _Block) and block.body == (_Text(text="A"),)
        (chained,) = block.inverse
        assert isinstance(chained, _Block) and chained.chained

    def test_a_trimmed_closing_tag_alone_on_its_line_drops_its_line_first(self) -> None:
        nodes = _parse("{{#if a}}\nBODY\n{{~/if}}\nTAIL")

        assert isinstance(nodes[0], _Block) and nodes[0].body == (_Text(text="BODY"),)
        assert nodes[1] == _Text(text="TAIL")

    def test_a_string_turns_only_an_escaped_quote_into_a_quote(self) -> None:
        quoted = _parse_expression('eq x "say \\"hi\\""').params[1]

        assert isinstance(quoted, _Literal) and quoted.text == 'say "hi"'
        with self.assertRaises(_Unconvertible):
            _parse_expression('eq x "C:\\temp"')

    @parameterized.expand(
        [
            ("deep_groups", "eq " + "(a " * 996 + "b"),
            ("braces_in_a_name", "if a{%b"),
            ("closing_braces_in_a_name", "a}}b"),
            ("quote_in_a_block_name", 'each xs as |x"|'),
        ]
    )
    def test_expressions_outside_the_grammar_are_refused(self, _name: str, body: str) -> None:
        with self.assertRaises(_Unconvertible):
            _parse_expression(body)

    @parameterized.expand(
        [
            ("unclosed_block", "{{#if a}}x"),
            ("mismatched_close", "{{#if a}}x{{/each}}"),
            ("two_else_tags", "{{#if a}}x{{else}}y{{else}}z{{/if}}"),
            ("unclosed_tag", "{{name"),
        ]
    )
    def test_malformed_templates_are_refused(self, _name: str, source: str) -> None:
        with self.assertRaises(_Malformed):
            _parse(source)
