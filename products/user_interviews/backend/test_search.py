from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.user_interviews.backend.models import UserInterview, UserInterviewTopic


class _FeatureFlagEnabledMixin(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestUserInterviewSearch(_FeatureFlagEnabledMixin):
    def setUp(self) -> None:
        super().setUp()
        self.topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic="Replay adoption",
            agent_context="ctx",
            questions=[],
        )
        self.interview_a = UserInterview.objects.create(
            team=self.team,
            topic=self.topic,
            interviewee_identifier="alex@example.com",
            interviewee_emails=["alex@example.com"],
            transcript="alex talked about session replay buffering",
            summary="alex finds session replay slow on long sessions",
            created_by=self.user,
        )
        self.interview_b = UserInterview.objects.create(
            team=self.team,
            topic=self.topic,
            interviewee_identifier="bob@example.com",
            interviewee_emails=["bob@example.com"],
            transcript="bob loves heatmaps but ignores replays",
            summary="bob uses heatmaps daily",
            created_by=self.user,
        )

    def _url(self) -> str:
        return f"/api/environments/{self.team.id}/user_interviews/search/"

    def _embedding_response(self) -> MagicMock:
        resp = MagicMock()
        resp.embedding = [0.0] * 3072
        resp.tokens_used = 4
        resp.did_truncate = False
        return resp

    def _hogql_rows(self, rows: list[tuple[Any, ...]]) -> MagicMock:
        result = MagicMock()
        result.results = rows
        return result

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_returns_ranked_matches(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows(
            [
                (str(self.interview_a.id), "transcript", 0.12),
                (str(self.interview_a.id), "summary", 0.22),
                (str(self.interview_b.id), "transcript", 0.48),
            ]
        )

        response = self.client.post(self._url(), {"query": "is session replay slow?"}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        body = response.json()
        self.assertEqual(len(body), 3)
        self.assertEqual(body[0]["interview_id"], str(self.interview_a.id))
        self.assertEqual(body[0]["document_type"], "transcript")
        self.assertAlmostEqual(body[0]["similarity"], 0.88, places=5)
        self.assertEqual(body[0]["content_snippet"], "alex talked about session replay buffering")
        self.assertEqual(body[0]["interviewee_identifier"], "alex@example.com")
        self.assertEqual(body[0]["topic_id"], str(self.topic.id))
        self.assertGreater(body[0]["similarity"], body[2]["similarity"])

        mock_embed.assert_called_once()
        embed_args, embed_kwargs = mock_embed.call_args
        self.assertEqual(embed_args[0], self.team)
        self.assertEqual(embed_args[1], "is session replay slow?")
        self.assertEqual(embed_kwargs["model"], "text-embedding-3-large-3072")

    @parameterized.expand(
        [
            ("distance_above_one_clamps_to_zero", 1.4, 0.0),
            ("negative_distance_clamps_to_one", -0.01, 1.0),
        ]
    )
    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_clamps_similarity_to_unit_interval(self, _name, distance, expected, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([(str(self.interview_a.id), "transcript", distance)])
        response = self.client.post(self._url(), {"query": "x"}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[0]["similarity"], expected)

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_snippet_reflects_current_postgres_content(self, mock_embed, mock_hogql):
        """The snippet must come from the live UserInterview row, not the embedding row's
        snapshot — otherwise editing or trimming a transcript leaves stale content visible
        through the search endpoint until the embedding ages out."""
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([(str(self.interview_a.id), "transcript", 0.1)])

        self.interview_a.transcript = "alex's edited transcript: replay is faster now"
        self.interview_a.save(update_fields=["transcript"])

        response = self.client.post(self._url(), {"query": "x"}, content_type="application/json")
        self.assertEqual(response.json()[0]["content_snippet"], "alex's edited transcript: replay is faster now")

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_truncates_long_content_snippet(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        self.interview_a.transcript = "x" * 1000
        self.interview_a.save(update_fields=["transcript"])
        mock_hogql.return_value = self._hogql_rows([(str(self.interview_a.id), "transcript", 0.1)])
        response = self.client.post(self._url(), {"query": "x"}, content_type="application/json")
        self.assertEqual(len(response.json()[0]["content_snippet"]), 500)

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_skips_rows_for_deleted_interviews(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        ghost_id = "00000000-0000-0000-0000-000000000000"
        mock_hogql.return_value = self._hogql_rows(
            [
                (str(self.interview_a.id), "transcript", 0.1),
                (ghost_id, "transcript", 0.2),
            ]
        )
        response = self.client.post(self._url(), {"query": "x"}, content_type="application/json")
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["interview_id"], str(self.interview_a.id))

    @parameterized.expand(
        [
            ("transcript_only", ["transcript"], {"transcript"}),
            ("summary_only", ["summary"], {"summary"}),
            ("both_explicit", ["transcript", "summary"], {"transcript", "summary"}),
        ]
    )
    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_forwards_document_types_filter(
        self, _name, document_types, expected_in_placeholders, mock_embed, mock_hogql
    ):
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])

        self.client.post(
            self._url(),
            {"query": "x", "document_types": document_types},
            content_type="application/json",
        )

        mock_hogql.assert_called_once()
        placeholders = mock_hogql.call_args.kwargs["placeholders"]
        self.assertEqual(set(placeholders["document_types"].value), expected_in_placeholders)

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_resolves_topic_id_via_current_postgres_linkage(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])

        self.client.post(
            self._url(),
            {"query": "x", "topic_id": str(self.topic.id)},
            content_type="application/json",
        )

        placeholders = mock_hogql.call_args.kwargs["placeholders"]
        # Both seeded interviews are currently linked to the topic; the search WHERE clause
        # is built from that *current* linkage, not from the embedding-time metadata snapshot.
        self.assertEqual(
            set(placeholders["scoped_document_ids"].value),
            {str(self.interview_a.id), str(self.interview_b.id)},
        )
        hogql_query = mock_hogql.call_args.kwargs["query"]
        self.assertIn("document_id IN {scoped_document_ids}", hogql_query)
        self.assertNotIn("JSONExtractString(metadata, 'topic_id')", hogql_query)

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_excludes_interviews_detached_from_topic(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])
        # Detach interview_b from the topic — its embedding row still names topic in metadata,
        # but the Postgres linkage is gone, so it must NOT appear in the scoped id set.
        self.interview_b.topic = None
        self.interview_b.save(update_fields=["topic"])

        self.client.post(
            self._url(),
            {"query": "x", "topic_id": str(self.topic.id)},
            content_type="application/json",
        )

        placeholders = mock_hogql.call_args.kwargs["placeholders"]
        self.assertEqual(set(placeholders["scoped_document_ids"].value), {str(self.interview_a.id)})

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_short_circuits_when_topic_has_no_interviews(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        # No call to HogQL should happen when the topic resolves to zero interview IDs.
        empty_topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["nobody@example.com"],
            topic="No interviews yet",
            agent_context="",
            questions=[],
        )

        response = self.client.post(
            self._url(),
            {"query": "x", "topic_id": str(empty_topic.id)},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])
        mock_hogql.assert_not_called()
        mock_embed.assert_not_called()

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_defaults_to_both_document_types_when_unset(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])

        self.client.post(self._url(), {"query": "x"}, content_type="application/json")

        placeholders = mock_hogql.call_args.kwargs["placeholders"]
        self.assertEqual(set(placeholders["document_types"].value), {"transcript", "summary"})

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_enforces_default_limit_when_omitted(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])

        self.client.post(self._url(), {"query": "x"}, content_type="application/json")

        placeholders = mock_hogql.call_args.kwargs["placeholders"]
        self.assertEqual(placeholders["limit"].value, 10)

    @parameterized.expand(
        [
            ("missing_query", {}),
            ("query_above_max_length", {"query": "x" * 2001}),
            ("limit_above_max", {"query": "x", "limit": 51}),
            ("invalid_document_type", {"query": "x", "document_types": ["nonsense"]}),
            ("empty_document_types_list", {"query": "x", "document_types": []}),
        ]
    )
    def test_search_rejects_invalid_request(self, _name, payload):
        response = self.client.post(self._url(), payload, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_action_declares_read_scope(self):
        from products.user_interviews.backend.presentation.views import UserInterviewViewSet

        self.assertEqual(UserInterviewViewSet.search.kwargs["required_scopes"], ["user_interview:read"])

    @patch("products.user_interviews.backend.presentation.views.tag_queries")
    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_tags_clickhouse_query_for_attribution(self, mock_embed, mock_hogql, mock_tag):
        from posthog.clickhouse.query_tagging import Feature, Product

        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])

        self.client.post(self._url(), {"query": "x"}, content_type="application/json")

        mock_tag.assert_called_once_with(product=Product.USER_INTERVIEWS, feature=Feature.SEMANTIC_SEARCH)

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch(
        "products.user_interviews.backend.presentation.views.generate_embedding",
        side_effect=RuntimeError("embedding service down"),
    )
    def test_search_returns_502_when_embedding_service_fails(self, _mock_embed, mock_hogql):
        response = self.client.post(self._url(), {"query": "x"}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Embedding service", response.json()["detail"])
        mock_hogql.assert_not_called()

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_caps_scoped_document_ids_for_pathological_topic_size(self, mock_embed, mock_hogql):
        from products.user_interviews.backend.presentation.views import SEARCH_TOPIC_INTERVIEW_CAP

        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])
        # Create enough interviews to exceed the cap. Generate them in a single batch.
        UserInterview.objects.bulk_create(
            [
                UserInterview(
                    team=self.team,
                    topic=self.topic,
                    interviewee_identifier=f"person-{i}@example.com",
                    interviewee_emails=[f"person-{i}@example.com"],
                    transcript="t",
                    summary="s",
                    created_by=self.user,
                )
                for i in range(SEARCH_TOPIC_INTERVIEW_CAP + 5)
            ]
        )

        self.client.post(
            self._url(),
            {"query": "x", "topic_id": str(self.topic.id)},
            content_type="application/json",
        )

        placeholders = mock_hogql.call_args.kwargs["placeholders"]
        self.assertEqual(len(placeholders["scoped_document_ids"].value), SEARCH_TOPIC_INTERVIEW_CAP)

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_ranks_distance_inside_subquery_to_avoid_ann_prefilter(self, mock_embed, mock_hogql):
        # Guards against collapsing the vector ranking back onto a flat
        # "ORDER BY cosineDistance(...) LIMIT n FROM document_embeddings". document_embeddings
        # is a shared table with an approximate vector index; a flat ORDER BY ... LIMIT makes
        # ClickHouse pick the globally-nearest rows via that index *before* the team/product
        # WHERE filter, so on a busy project this team's interviews get filtered out and the
        # search returns []. The distance must be computed and ranked in a subquery so the
        # outer ORDER BY sits on the alias, not on the raw scan.
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])

        self.client.post(self._url(), {"query": "x"}, content_type="application/json")

        query = mock_hogql.call_args.kwargs["query"]
        self.assertIn("FROM (", query)
        outer = query[query.rindex(")") :]
        self.assertIn("ORDER BY distance", outer)
        self.assertNotIn("cosineDistance", outer)

    @patch("products.user_interviews.backend.presentation.views.execute_hogql_query")
    @patch("products.user_interviews.backend.presentation.views.generate_embedding")
    def test_search_does_not_leak_across_teams(self, mock_embed, mock_hogql):
        mock_embed.return_value = self._embedding_response()
        mock_hogql.return_value = self._hogql_rows([])

        self.client.post(self._url(), {"query": "x"}, content_type="application/json")

        placeholders = mock_hogql.call_args.kwargs["placeholders"]
        self.assertEqual(placeholders["team_id"].value, self.team.id)
