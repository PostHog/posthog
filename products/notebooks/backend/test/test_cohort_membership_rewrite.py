from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog import redis

from products.notebooks.backend.cohort_membership_rewrite import rewrite_cohort_membership_queries
from products.notebooks.backend.collab_stream import STREAM_KEY_PATTERN
from products.notebooks.backend.models import Notebook


class TestCohortMembershipRewrite(BaseTest):
    @parameterized.expand([("dry_run", False, []), ("apply", True, [b"1-1"])])
    def test_publishes_the_new_version_to_the_collab_stream(
        self, _name: str, apply: bool, expected_entries: list[bytes]
    ) -> None:
        sql = "SELECT person_id FROM cohort_membership WHERE cohort_id = 7"
        notebook = Notebook.objects.create(
            team=self.team,
            content={
                "type": "doc",
                "content": [{"type": "ph-query", "attrs": {"query": {"kind": "HogQLQuery", "query": sql}}}],
            },
        )

        rewrite_cohort_membership_queries(self.team.pk, apply)

        stream_key = STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id=notebook.short_id)
        assert [entry_id for entry_id, _ in redis.get_client().xrange(stream_key)] == expected_entries
