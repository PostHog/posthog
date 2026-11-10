from unittest import TestCase

from products.notebooks.backend.util import (
    extract_referenced_insight_short_ids,
    filter_notebook_content_for_sharing,
    iter_markdown_blocks,
)


class TestColumnLayout(TestCase):
    def test_sharing_preserves_columns_and_filters_each_inner_component(self) -> None:
        markdown = "\n\n".join(
            [
                '<Columns widths={[2, 1]} privateProp="remove-me">',
                "<Column>",
                "## First chart",
                '<Query nodeId="demo-chart" query={{"kind":"SavedInsightNode","shortId":"demo-first"}} />',
                "</Column>",
                "<Column>",
                "Notes next to the chart.",
                '<PythonV2 code="private code" />',
                "</Column>",
                "</Columns>",
            ]
        )
        content = {
            "type": "doc",
            "content": [{"type": "ph-markdown-notebook", "attrs": {"markdown": markdown}}],
        }
        self.assertEqual(extract_referenced_insight_short_ids(content), {"demo-first"})
        shared = filter_notebook_content_for_sharing(content)["content"][0]["attrs"]["markdown"]
        self.assertIn("<Columns widths={[2,1]}>", shared)
        self.assertIn("</Columns>", shared)
        self.assertIn("Notes next to the chart.", shared)
        self.assertIn("<PythonV2 />", shared)
        self.assertNotIn("private code", shared)
        self.assertNotIn("remove-me", shared)
        query = next(block for block in iter_markdown_blocks(markdown) if block.tag_name == "Query")
        self.assertEqual(query.node_id, "demo-chart")
        self.assertEqual(markdown[query.start : query.end], query.source)
