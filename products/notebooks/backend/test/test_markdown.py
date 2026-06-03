from posthog.test.base import BaseTest

from products.notebooks.backend.markdown import markdown_to_text_content, markdown_to_tiptap_doc, tiptap_doc_to_markdown


class TestNotebookMarkdown(BaseTest):
    def test_markdown_query_tag_round_trips_to_notebook_node(self):
        markdown = """# Report

Text before.

<Query title="Weekly signups">
{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]}}
</Query>
"""

        doc = markdown_to_tiptap_doc(markdown, title="Report")

        assert doc["content"][0]["type"] == "heading"
        query_node = doc["content"][2]
        assert query_node["type"] == "ph-query"
        assert query_node["attrs"]["title"] == "Weekly signups"
        assert query_node["attrs"]["query"]["kind"] == "InsightVizNode"

        exported = tiptap_doc_to_markdown(doc)
        assert '<Query title="Weekly signups">' in exported
        assert '"kind": "InsightVizNode"' in exported

    def test_resource_tags_map_to_notebook_nodes(self):
        markdown = """
<FeatureFlag id="12" />
<Experiment id="34" />
<Survey id="survey-uuid" />
<SessionReplay id="session-1" />
<Insight id="abc123" />
"""

        doc = markdown_to_tiptap_doc(markdown)
        node_types = [node["type"] for node in doc["content"]]

        assert node_types == ["ph-feature-flag", "ph-experiment", "ph-survey", "ph-recording", "ph-query"]
        assert doc["content"][0]["attrs"]["id"] == 12
        assert doc["content"][4]["attrs"]["query"] == {"kind": "SavedInsightNode", "shortId": "abc123"}

    def test_resource_tags_inside_block_tags_are_not_parsed_twice(self):
        markdown = """<Query>
{"kind": "InsightVizNode", "note": "<FeatureFlag id=\\"12\\" />"}
</Query>"""

        doc = markdown_to_tiptap_doc(markdown)

        assert len(doc["content"]) == 1
        assert doc["content"][0]["type"] == "ph-query"
        assert doc["content"][0]["attrs"]["query"]["note"] == '<FeatureFlag id="12" />'

    def test_generic_notebook_node_tag_round_trips(self):
        markdown = '<NotebookNode type="ph-usage-metrics">\n{"dateRange": "7d"}\n</NotebookNode>'

        doc = markdown_to_tiptap_doc(markdown)

        assert doc["content"][0] == {
            "type": "ph-usage-metrics",
            "attrs": {"dateRange": "7d"},
        }
        assert tiptap_doc_to_markdown(doc) == (
            '<NotebookNode type="ph-usage-metrics">\n{\n  "dateRange": "7d"\n}\n</NotebookNode>'
        )

    def test_text_content_uses_markdown_body(self):
        markdown = """# Ignored duplicate

Important summary.

<FeatureFlag id="12" />
"""

        assert (
            markdown_to_text_content(markdown, title="Ignored duplicate")
            == "Ignored duplicate\nImportant summary.\nFeatureFlag 12"
        )
