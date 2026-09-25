from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from posthog.errors import CHQueryErrorUnknownTable
from posthog.models import Team

from products.tracing.backend.has_spans_query_runner import HasSpansQueryRunner, team_has_spans


class TestHasSpansQueryRunner(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.team = Team(id=4711)
        cache.delete(f"team:{self.team.id}:has_spans")

    def test_returns_false_when_the_span_table_is_missing(self):
        with patch(
            "products.tracing.backend.has_spans_query_runner.execute_hogql_query",
            side_effect=CHQueryErrorUnknownTable("Table posthog.trace_spans does not exist", code=60),
        ):
            self.assertFalse(HasSpansQueryRunner(self.team).run())

    def test_does_not_cache_a_negative_result(self):
        with patch.object(HasSpansQueryRunner, "run", return_value=False) as mock_run:
            self.assertFalse(team_has_spans(self.team))
            self.assertFalse(team_has_spans(self.team))

        self.assertEqual(mock_run.call_count, 2)
