import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest import TestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import SharingConfiguration

from products.notebooks.backend.models import Notebook
from products.notebooks.backend.util import (
    extract_inline_query_nodes,
    extract_referenced_insight_short_ids,
    filter_notebook_content_for_sharing,
    iter_prosemirror_nodes,
)
from products.product_analytics.backend.models.insight import Insight


def _saved_insight_query_node(short_id: str) -> dict[str, Any]:
    return {
        "type": "ph-query",
        "attrs": {"query": {"kind": "SavedInsightNode", "shortId": short_id}},
    }


def _ad_hoc_query_node(kind: str = "DataTableNode", node_id: str | None = "node-1") -> dict[str, Any]:
    attrs: dict[str, Any] = {"query": {"kind": kind, "source": {"kind": "EventsQuery", "select": ["*"]}}}
    if node_id is not None:
        attrs["nodeId"] = node_id
    return {
        "type": "ph-query",
        "attrs": attrs,
    }


def _doc(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(nodes)}


def _markdown_doc(markdown: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "ph-markdown-notebook",
                "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown},
            }
        ],
    }


class TestExtractReferencedInsightShortIds(TestCase):
    @parameterized.expand(
        [
            ("none", None, set()),
            ("not_a_dict", "not a doc", set()),
            ("empty_doc", {"type": "doc", "content": []}, set()),
            ("doc_without_content_array", {"type": "doc"}, set()),
            (
                "single_saved_insight",
                _doc(_saved_insight_query_node("abc123")),
                {"abc123"},
            ),
            (
                "ad_hoc_query_ignored",
                _doc(_ad_hoc_query_node()),
                set(),
            ),
            (
                "deduplicates_repeated_short_ids",
                _doc(_saved_insight_query_node("abc"), _saved_insight_query_node("abc")),
                {"abc"},
            ),
            (
                "ignores_non_query_nodes",
                _doc(
                    {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]},
                    _saved_insight_query_node("xyz"),
                    {"type": "ph-image", "attrs": {"src": "x"}},
                ),
                {"xyz"},
            ),
            (
                "walks_nested_content",
                _doc(
                    {
                        "type": "blockquote",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [_saved_insight_query_node("nested1")],
                            }
                        ],
                    },
                    _saved_insight_query_node("top"),
                ),
                {"nested1", "top"},
            ),
            (
                "missing_attrs_skipped",
                _doc({"type": "ph-query"}),
                set(),
            ),
            (
                "empty_short_id_skipped",
                _doc(
                    {
                        "type": "ph-query",
                        "attrs": {"query": {"kind": "SavedInsightNode", "shortId": ""}},
                    }
                ),
                set(),
            ),
            (
                "non_string_short_id_skipped",
                _doc(
                    {
                        "type": "ph-query",
                        "attrs": {"query": {"kind": "SavedInsightNode", "shortId": 123}},
                    }
                ),
                set(),
            ),
            (
                "markdown_saved_insight",
                _markdown_doc('<Query hideFilters query={{"kind":"SavedInsightNode","shortId":"abc123"}} />'),
                {"abc123"},
            ),
            (
                "markdown_saved_insight_with_string_query",
                _markdown_doc('<Query query="{\\"kind\\":\\"SavedInsightNode\\",\\"shortId\\":\\"abc123\\"}" />'),
                {"abc123"},
            ),
            (
                "markdown_saved_insight_with_even_backslashes_before_quote",
                _markdown_doc(r'<Query query={{"kind":"SavedInsightNode","shortId":"abc123","path":"C:\\\\"}} />'),
                {"abc123"},
            ),
            (
                "markdown_query_inside_code_block_ignored",
                _markdown_doc('```md\n<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />\n```'),
                set(),
            ),
        ]
    )
    def test_extract(self, _name: str, content: Any, expected: set[str]) -> None:
        self.assertEqual(extract_referenced_insight_short_ids(content), expected)

    def test_iter_prosemirror_nodes_handles_malformed_children(self) -> None:
        doc = {"type": "doc", "content": "this is not a list"}
        self.assertEqual(list(iter_prosemirror_nodes(doc)), [doc])

    def test_extract_handles_stringified_query_attr(self) -> None:
        doc = _doc(
            {
                "type": "ph-query",
                "attrs": {"query": json.dumps({"kind": "SavedInsightNode", "shortId": "abc123"})},
            }
        )
        self.assertEqual(extract_referenced_insight_short_ids(doc), {"abc123"})


class TestExtractInlineQueryNodes(TestCase):
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty_doc", {"type": "doc", "content": []}, []),
            (
                "saved_insight_excluded",
                _doc(_saved_insight_query_node("abc123")),
                [],
            ),
            (
                "single_inline_query",
                _doc(_ad_hoc_query_node(node_id="node-1")),
                [("node-1", {"kind": "DataTableNode", "source": {"kind": "EventsQuery", "select": ["*"]}})],
            ),
            (
                "missing_node_id_skipped",
                _doc(_ad_hoc_query_node(node_id=None)),
                [],
            ),
            (
                "empty_node_id_skipped",
                _doc(_ad_hoc_query_node(node_id="")),
                [],
            ),
            (
                "saved_insight_and_inline_mixed",
                _doc(
                    _saved_insight_query_node("abc123"),
                    _ad_hoc_query_node(kind="HogQLQuery", node_id="node-2"),
                ),
                [
                    (
                        "node-2",
                        {"kind": "HogQLQuery", "source": {"kind": "EventsQuery", "select": ["*"]}},
                    ),
                ],
            ),
            (
                "deeply_nested_inline_query",
                _doc(
                    {
                        "type": "blockquote",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [_ad_hoc_query_node(node_id="deep-node")],
                            }
                        ],
                    }
                ),
                [("deep-node", {"kind": "DataTableNode", "source": {"kind": "EventsQuery", "select": ["*"]}})],
            ),
            (
                "markdown_inline_query_with_explicit_node_id",
                _markdown_doc(
                    '<Query nodeId="inline-node-1" query={{"kind":"DataTableNode","source":{"kind":"EventsQuery","select":["event"]}}} />'
                ),
                [("inline-node-1", {"kind": "DataTableNode", "source": {"kind": "EventsQuery", "select": ["event"]}})],
            ),
            (
                "markdown_inline_query_with_derived_node_id",
                _markdown_doc(
                    '<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery","select":["event"],"after":"-24h","limit":1}}} />'
                ),
                [
                    (
                        "mdn-197jp5a-0",
                        {
                            "kind": "DataTableNode",
                            "source": {"kind": "EventsQuery", "select": ["event"], "after": "-24h", "limit": 1},
                        },
                    )
                ],
            ),
            (
                "markdown_inline_query_with_even_backslashes_before_quote",
                _markdown_doc(
                    r'<Query nodeId="inline-node-1" query={{"kind":"DataTableNode","source":{"kind":"EventsQuery","select":["event"],"path":"C:\\\\"}}} />'
                ),
                [
                    (
                        "inline-node-1",
                        {
                            "kind": "DataTableNode",
                            "source": {"kind": "EventsQuery", "select": ["event"], "path": "C:\\\\"},
                        },
                    )
                ],
            ),
        ]
    )
    def test_extract(self, _name: str, content: Any, expected: list[tuple[str, dict[str, Any]]]) -> None:
        self.assertEqual(extract_inline_query_nodes(content), expected)

    def test_extract_handles_stringified_query_attr(self) -> None:
        doc = _doc(
            {
                "type": "ph-query",
                "attrs": {
                    "nodeId": "node-1",
                    "query": json.dumps({"kind": "DataTableNode", "source": {"kind": "EventsQuery", "select": ["*"]}}),
                },
            }
        )
        self.assertEqual(
            extract_inline_query_nodes(doc),
            [("node-1", {"kind": "DataTableNode", "source": {"kind": "EventsQuery", "select": ["*"]}})],
        )


class TestFilterNotebookContentForSharing(TestCase):
    @parameterized.expand(
        [
            ("none", None, None),
            ("not_a_dict", "not a doc", "not a doc"),
            (
                "builtin_nodes_pass_through",
                _doc(
                    {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]},
                    {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "h"}]},
                ),
                _doc(
                    {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]},
                    {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "h"}]},
                ),
            ),
            (
                "allow_listed_widgets_keep_attrs",
                _doc(
                    {"type": "ph-image", "attrs": {"src": "x"}},
                    {"type": "ph-latex", "attrs": {"content": "E=mc^2"}},
                    {"type": "ph-embed", "attrs": {"src": "https://example.com"}},
                    _saved_insight_query_node("abc123"),
                ),
                _doc(
                    {"type": "ph-image", "attrs": {"src": "x"}},
                    {"type": "ph-latex", "attrs": {"content": "E=mc^2"}},
                    {"type": "ph-embed", "attrs": {"src": "https://example.com"}},
                    _saved_insight_query_node("abc123"),
                ),
            ),
            (
                "unsupported_widget_attrs_stripped",
                _doc(
                    {"type": "ph-python", "attrs": {"code": "SECRET"}},
                    {"type": "ph-duck-sql", "attrs": {"code": "SELECT *", "duckExecution": {"tableData": [[1]]}}},
                    {"type": "ph-recording", "attrs": {"id": "rec-1"}},
                    {"type": "ph-feature-flag", "attrs": {"id": 42}},
                    {"type": "ph-llm-trace", "attrs": {"id": "trace-1"}},
                ),
                _doc(
                    {"type": "ph-python"},
                    {"type": "ph-duck-sql"},
                    {"type": "ph-recording"},
                    {"type": "ph-feature-flag"},
                    {"type": "ph-llm-trace"},
                ),
            ),
            (
                "unsupported_widget_child_content_dropped",
                _doc(
                    {
                        "type": "ph-zendesk-tickets",
                        "attrs": {"query": "customer:acme"},
                        "content": [{"type": "text", "text": "leaked"}],
                    },
                ),
                _doc({"type": "ph-zendesk-tickets"}),
            ),
            (
                "nested_unsupported_widget_stripped",
                _doc(
                    {
                        "type": "blockquote",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "keep"}]},
                            {"type": "ph-python", "attrs": {"code": "SECRET"}},
                        ],
                    }
                ),
                _doc(
                    {
                        "type": "blockquote",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "keep"}]},
                            {"type": "ph-python"},
                        ],
                    }
                ),
            ),
            (
                "markdown_notebook_keeps_safe_components_and_strips_unsupported_props",
                _markdown_doc(
                    "\n\n".join(
                        [
                            '<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />',
                            '<Embed src="https://posthog.com" />',
                            '<Python code="SECRET = true" />',
                            '<Chat messages={{["secret"]}} />',
                        ]
                    )
                ),
                _markdown_doc(
                    "\n\n".join(
                        [
                            '<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />',
                            '<Embed src="https://posthog.com" />',
                            "<Python />",
                            "<Chat />",
                        ]
                    )
                ),
            ),
        ]
    )
    def test_filter(self, _name: str, content: Any, expected: Any) -> None:
        self.assertEqual(filter_notebook_content_for_sharing(content), expected)

    def test_filter_does_not_mutate_input(self) -> None:
        original = _doc({"type": "ph-python", "attrs": {"code": "SECRET"}})
        snapshot = {"type": "doc", "content": [{"type": "ph-python", "attrs": {"code": "SECRET"}}]}
        filter_notebook_content_for_sharing(original)
        self.assertEqual(original, snapshot)


class TestNotebookSharingConfiguration(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, title="My notebook", created_by=self.user)

    def _sharing_url(self, short_id: str | None = None) -> str:
        short_id = short_id or self.notebook.short_id
        return f"/api/projects/{self.team.id}/notebooks/{short_id}/sharing/"

    def test_get_sharing_returns_disabled_by_default(self) -> None:
        response = self.client.get(self._sharing_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertFalse(body["enabled"])
        # An access token is generated even before saving so the UI can display it
        self.assertIsNotNone(body["access_token"])

    def test_enable_sharing_persists_and_grants_token(self) -> None:
        response = self.client.patch(self._sharing_url(), {"enabled": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertTrue(body["enabled"])
        access_token = body["access_token"]
        config = SharingConfiguration.objects.get(notebook=self.notebook, team=self.team)
        self.assertTrue(config.enabled)
        self.assertEqual(config.access_token, access_token)

    def test_refresh_rotates_access_token_and_keeps_notebook_link(self) -> None:
        self.client.patch(self._sharing_url(), {"enabled": True}, format="json")
        original = SharingConfiguration.objects.get(notebook=self.notebook, expires_at__isnull=True)

        response = self.client.post(f"{self._sharing_url()}refresh/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        original.refresh_from_db()
        self.assertIsNotNone(original.expires_at)

        new_config = SharingConfiguration.objects.get(notebook=self.notebook, expires_at__isnull=True)
        self.assertNotEqual(new_config.access_token, original.access_token)
        self.assertEqual(new_config.notebook_id, self.notebook.id)

    def test_unknown_notebook_returns_404(self) -> None:
        response = self.client.get(self._sharing_url(short_id="nope"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_shared_notebook_strips_unsupported_node_attrs(self) -> None:
        self.notebook.content = _doc(
            {"type": "paragraph", "content": [{"type": "text", "text": "hi"}]},
            {"type": "ph-image", "attrs": {"src": "https://example.com/x.png"}},
            {"type": "ph-python", "attrs": {"code": "SECRET = 'sk-...'"}},
            {
                "type": "ph-duck-sql",
                "attrs": {
                    "code": "SELECT email, mrr FROM stripe.customers",
                    "duckExecution": {"tableData": [["alice@acme.com", 12000]]},
                },
            },
            {"type": "ph-recording", "attrs": {"id": "01893f8c-some-recording"}},
        )
        self.notebook.text_content = "hi SECRET = 'sk-...' SELECT email, mrr FROM stripe.customers"
        self.notebook.save()
        self.client.patch(self._sharing_url(), {"enabled": True}, format="json")
        config = SharingConfiguration.objects.get(notebook=self.notebook, expires_at__isnull=True)

        # Hit the public viewer endpoint as an anonymous client
        self.client.logout()
        response = self.client.get(f"/shared/{config.access_token}.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(body["type"], "scene")
        self.assertIn("notebook", body)
        self.assertEqual(body["notebook"]["short_id"], self.notebook.short_id)
        self.assertEqual(body["notebook"]["title"], "My notebook")

        nodes = body["notebook"]["content"]["content"]
        self.assertEqual(nodes[0], {"type": "paragraph", "content": [{"type": "text", "text": "hi"}]})
        self.assertEqual(nodes[1], {"type": "ph-image", "attrs": {"src": "https://example.com/x.png"}})
        self.assertEqual(nodes[2], {"type": "ph-python"})
        self.assertEqual(nodes[3], {"type": "ph-duck-sql"})
        self.assertEqual(nodes[4], {"type": "ph-recording"})

        # Defense in depth: catch any future field we forget to scrub.
        raw = response.content.decode()
        self.assertNotIn("SECRET", raw)
        self.assertNotIn("sk-...", raw)
        self.assertNotIn("stripe.customers", raw)
        self.assertNotIn("alice@acme.com", raw)
        self.assertNotIn("01893f8c-some-recording", raw)
        self.assertIsNone(body["notebook"]["text_content"])

    def test_shared_notebook_strips_unsupported_markdown_component_props(self) -> None:
        markdown = "\n\n".join(
            [
                "hello",
                '<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />',
                '<Python code="SECRET = true" />',
                '<Chat messages={{["SECRET_CHAT"]}} />',
            ]
        )
        self.notebook.content = _doc(
            {"type": "paragraph", "content": [{"type": "text", "text": "hi"}]},
            {
                "type": "blockquote",
                "content": [
                    {
                        "type": "ph-markdown-notebook",
                        "attrs": {
                            "nodeId": "markdown-notebook-v2",
                            "markdown": markdown,
                            "runtimeState": {"secret": "SECRET_RUNTIME"},
                        },
                    }
                ],
            },
        )
        self.notebook.text_content = "hi SECRET = true SECRET_CHAT SECRET_RUNTIME"
        self.notebook.save()
        self.client.patch(self._sharing_url(), {"enabled": True}, format="json")
        config = SharingConfiguration.objects.get(notebook=self.notebook, expires_at__isnull=True)

        self.client.logout()
        response = self.client.get(f"/shared/{config.access_token}.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()

        markdown_node = body["notebook"]["content"]["content"][1]["content"][0]
        self.assertEqual(
            markdown_node,
            {
                "type": "ph-markdown-notebook",
                "attrs": {
                    "nodeId": "markdown-notebook-v2",
                    "markdown": "\n\n".join(
                        [
                            "hello",
                            '<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />',
                            "<Python />",
                            "<Chat />",
                        ]
                    ),
                },
            },
        )

        raw = response.content.decode()
        self.assertNotIn("SECRET", raw)
        self.assertNotIn("SECRET_CHAT", raw)
        self.assertNotIn("SECRET_RUNTIME", raw)
        self.assertIsNone(body["notebook"]["text_content"])

    def test_shared_notebook_reserializes_allowlisted_markdown_component_props(self) -> None:
        markdown = "\n\n".join(
            [
                "hello",
                (
                    '<Embed src="https://posthog.com" title="Public docs" height={320} '
                    'unsafe="&lt;Python code=&quot;SECRET_EMBED&quot; /&gt;" '
                    'cachedResults={{"rows":["SECRET_CACHE"]}} />'
                ),
            ]
        )
        self.notebook.content = _markdown_doc(markdown)
        self.notebook.text_content = "hello SECRET_EMBED SECRET_CACHE"
        self.notebook.save()
        self.client.patch(self._sharing_url(), {"enabled": True}, format="json")
        config = SharingConfiguration.objects.get(notebook=self.notebook, expires_at__isnull=True)

        self.client.logout()
        response = self.client.get(f"/shared/{config.access_token}.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()

        markdown_node = body["notebook"]["content"]["content"][0]
        self.assertEqual(
            markdown_node,
            {
                "type": "ph-markdown-notebook",
                "attrs": {
                    "nodeId": "markdown-notebook-v2",
                    "markdown": "\n\n".join(
                        [
                            "hello",
                            '<Embed height={320} src="https://posthog.com" title="Public docs" />',
                        ]
                    ),
                },
            },
        )

        raw = response.content.decode()
        self.assertNotIn("SECRET_EMBED", raw)
        self.assertNotIn("SECRET_CACHE", raw)
        self.assertNotIn("unsafe", raw)
        self.assertNotIn("cachedResults", raw)
        self.assertIsNone(body["notebook"]["text_content"])

    def test_deleted_notebook_404s_on_shared_endpoint(self) -> None:
        self.client.patch(self._sharing_url(), {"enabled": True}, format="json")
        config = SharingConfiguration.objects.get(notebook=self.notebook, expires_at__isnull=True)
        self.notebook.deleted = True
        self.notebook.save()

        self.client.logout()
        response = self.client.get(f"/shared/{config.access_token}.json")
        # The viewer raises NotFound which is rendered as a custom 404 HTML page for non-json paths,
        # but the .json variant returns the standard DRF 404.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestNotebookSharingGrantsInsightAccess(APIBaseTest):
    """A notebook's sharing access token should grant read access to the saved insights it embeds."""

    def setUp(self) -> None:
        super().setUp()
        self.referenced_insight = Insight.objects.create(team=self.team, name="Referenced", short_id="ref0001")
        self.unreferenced_insight = Insight.objects.create(team=self.team, name="Unreferenced", short_id="unr0001")
        self.notebook = Notebook.objects.create(
            team=self.team,
            title="Notebook with insight",
            content=_doc(_saved_insight_query_node("ref0001")),
            created_by=self.user,
        )
        self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/sharing/",
            {"enabled": True},
            format="json",
        )
        self.config = SharingConfiguration.objects.get(notebook=self.notebook, expires_at__isnull=True)

    def test_get_connected_insight_ids_includes_referenced_insight(self) -> None:
        self.assertEqual(self.config.get_connected_insight_ids(), [self.referenced_insight.id])

    def test_get_connected_insight_ids_excludes_unreferenced_insight(self) -> None:
        self.assertNotIn(self.unreferenced_insight.id, self.config.get_connected_insight_ids())

    def test_can_access_object_for_referenced_insight(self) -> None:
        self.assertTrue(self.config.can_access_object(self.referenced_insight))
        self.assertFalse(self.config.can_access_object(self.unreferenced_insight))

    def test_deleted_referenced_insight_drops_from_grant(self) -> None:
        self.referenced_insight.deleted = True
        self.referenced_insight.save()
        self.assertEqual(self.config.get_connected_insight_ids(), [])

    def test_editing_notebook_updates_grant(self) -> None:
        # Initially only ref0001 is granted
        self.assertEqual(self.config.get_connected_insight_ids(), [self.referenced_insight.id])

        # Edit the notebook to also reference unr0001
        self.notebook.content = _doc(
            _saved_insight_query_node("ref0001"),
            _saved_insight_query_node("unr0001"),
        )
        self.notebook.save()

        # Re-fetch the config so the cached `self.config.notebook` doesn't mask the edit
        config = SharingConfiguration.objects.select_related("notebook").get(pk=self.config.pk)
        self.assertCountEqual(
            config.get_connected_insight_ids(),
            [self.referenced_insight.id, self.unreferenced_insight.id],
        )

    def test_anonymous_request_with_share_token_can_load_referenced_insight(self) -> None:
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/?short_id={self.referenced_insight.short_id}"
            f"&sharing_access_token={self.config.access_token}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["short_id"], self.referenced_insight.short_id)

    def test_shared_notebook_renders_when_inline_query_execution_fails(self) -> None:
        """If a single inline query fails server-side it must NOT 404 the whole notebook payload.
        The node is omitted from `inline_query_results`; the frontend falls back to a placeholder.
        Regression test: previously an inline query that needed a schema upgrade would crash
        the entire shared render path."""
        # Use a deliberately malformed query so process_query_dict raises during validation.
        # The viewer endpoint must still return 200 with the rest of the payload intact.
        self.notebook.content = _doc(
            {
                "type": "ph-query",
                "attrs": {
                    "nodeId": "broken-node",
                    "query": {"kind": "DataTableNode", "source": {"kind": "NotARealQueryKind"}},
                },
            },
        )
        self.notebook.save()

        self.client.logout()
        response = self.client.get(f"/shared/{self.config.access_token}.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertIn("notebook", body)
        self.assertEqual(body["notebook"]["short_id"], self.notebook.short_id)
        # The broken node is omitted from the result map but the rest of the response is intact.
        self.assertNotIn("broken-node", body.get("inline_query_results", {}))

    def test_shared_notebook_payload_inlines_inline_query_results(self) -> None:
        """Inline (non-saved-insight) ph-query nodes get pre-computed and inlined too, keyed by
        nodeId. Without this the shared viewer would POST `/query/` and bounce off the sharing
        token. We don't assert specific result contents — just that the map is built and shaped."""
        # Add an inline DataTableNode alongside the saved-insight one already on the notebook.
        self.notebook.content = _doc(
            _saved_insight_query_node("ref0001"),
            {
                "type": "ph-query",
                "attrs": {
                    "nodeId": "inline-node-1",
                    "query": {
                        "kind": "DataTableNode",
                        "source": {"kind": "EventsQuery", "select": ["event", "timestamp"]},
                    },
                },
            },
        )
        self.notebook.save()

        self.client.logout()
        response = self.client.get(f"/shared/{self.config.access_token}.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertIn("inline_query_results", body)
        self.assertIn("inline-node-1", body["inline_query_results"])
        inline_result = body["inline_query_results"]["inline-node-1"]
        self.assertIsInstance(inline_result, dict)
        # Must be a real query response, not a CacheMissResponse — otherwise the frontend
        # renders an empty `<Query cachedResults={...} inSharedMode />`, throws, and the
        # SharedNodeErrorBoundary swaps in the "unsupported node" placeholder. This is the
        # bug that made inline insights appear broken on the first shared-notebook view and
        # "fix themselves" after a few reloads (once the async cache finished warming).
        self.assertIn("results", inline_result)
        self.assertFalse(inline_result.get("error"))

    def test_shared_notebook_payload_inlines_referenced_insights(self) -> None:
        """The shared notebook payload pre-serializes every referenced saved insight so the
        viewer can render results without ever calling POST /query/ (which sharing tokens
        cannot reach)."""
        self.client.logout()
        response = self.client.get(f"/shared/{self.config.access_token}.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertIn("insights", body)
        self.assertIn("ref0001", body["insights"])
        self.assertNotIn("unr0001", body["insights"])
        # The serialized payload must include `result` so the frontend can seed `cachedResults`
        # — if it's missing, dataNodeLogic would try to POST /query/ at render time.
        self.assertIn("result", body["insights"]["ref0001"])

    def test_shared_markdown_notebook_payload_inlines_referenced_insights(self) -> None:
        self.notebook.content = _markdown_doc(
            '<Query hideFilters query={{"kind":"SavedInsightNode","shortId":"ref0001"}} />'
        )
        self.notebook.save()

        self.client.logout()
        response = self.client.get(f"/shared/{self.config.access_token}.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertIn("insights", body)
        self.assertIn("ref0001", body["insights"])
        self.assertNotIn("unr0001", body["insights"])
        self.assertIn("result", body["insights"]["ref0001"])
        self.assertIn("ph-markdown-notebook", response.content.decode())

    def test_shared_markdown_notebook_payload_inlines_inline_query_results(self) -> None:
        self.notebook.content = _markdown_doc(
            '<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery","select":["event"],"after":"-24h","limit":1}}} />'
        )
        self.notebook.save()

        self.client.logout()
        response = self.client.get(f"/shared/{self.config.access_token}.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertIn("inline_query_results", body)
        self.assertIn("mdn-197jp5a-0", body["inline_query_results"])
        inline_result = body["inline_query_results"]["mdn-197jp5a-0"]
        self.assertIsInstance(inline_result, dict)
        self.assertIn("results", inline_result)
        self.assertFalse(inline_result.get("error"))

    def test_anonymous_request_with_share_token_cannot_load_unreferenced_insight(self) -> None:
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/?short_id={self.unreferenced_insight.short_id}"
            f"&sharing_access_token={self.config.access_token}"
        )
        # Either filtered out (200 with empty results) or 404 — both are acceptable proof of denial
        if response.status_code == status.HTTP_200_OK:
            self.assertEqual(response.json()["results"], [])
        else:
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
