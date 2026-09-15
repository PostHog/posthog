import unittest

from parameterized import parameterized

from products.slack_app.backend.services.slack_messages import strip_object_tags


class TestStripObjectTags(unittest.TestCase):
    @parameterized.expand(
        [
            ("inline_element", 'Before <insight id="1">hidden label</insight> after.', "Before  after."),
            ("SQL_payload", '<hogql title="Daily signups" label="Fallback" display="block">SELECT 1</hogql>', ""),
            ("SQL_alias", "<sql>SELECT 1</sql>", ""),
            ("self_closing_block", '<replay id="example" title="Recording" display="block"/>', ""),
            ("single_quoted_attributes", "<insight id='example'>Hidden</insight>", ""),
            ("nested_same_kind", "<insight>outer<insight>inner</insight>tail</insight>Kept", "Kept"),
            ("nested_other_kind", "<insight>outer<report>inner</report>tail</insight>Kept", "Kept"),
            ("consecutive_elements", "<insight>One</insight><hogql>SELECT 1</hogql>Kept", "Kept"),
            ("unfinished_body", 'Before <hogql title="Hidden">SELECT', "Before "),
            ("stray_closing_tag", "Before </insight> after", "Before  after"),
            ("inline_code", "Use `<insight>Hidden</insight>`.", "Use ``."),
            ("fenced_code", "```xml\n<insight>Hidden</insight>\n```", "```xml\n\n```"),
            ("mixed_code", "~~~\nKeep this.\n<insight>Hidden</insight>\n~~~", "~~~\nKeep this.\n\n~~~"),
            ("unknown_markup", "<summary>Keep this</summary>", "<summary>Keep this</summary>"),
            ("encoded_mention_in_title", '<insight title="&lt;!channel&gt;">Hidden</insight>', ""),
            ("raw_mention_in_body", "<insight><!here></insight>", ""),
            ("explicit_mention", "<!here>", "<!here>"),
            ("empty_text", "", ""),
        ]
    )
    def test_strip(self, _name: str, text: str, expected: str) -> None:
        assert strip_object_tags(text) == expected
