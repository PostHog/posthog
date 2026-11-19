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
