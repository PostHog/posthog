from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status


class TestMalformedQueryBody(APIBaseTest):
    @parameterized.expand(
        [
            ("query", "query"),
            ("sparkline", "sparkline"),
            ("facet_values", "facet_values"),
            ("count", "count"),
            ("count_ranges", "count-ranges"),
            ("services", "services"),
            ("patterns", "patterns"),
            ("patterns_diff", "patterns_diff"),
            ("group_by", "group-by"),
            ("export", "export"),
        ]
    )
    def test_string_query_body_returns_400(self, _name: str, url_path: str) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/{url_path}",
            data={"query": "not-an-object"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
