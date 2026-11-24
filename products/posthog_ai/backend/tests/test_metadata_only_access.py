import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.data_access_policy import METADATA_ONLY_SCOPE
from posthog.models import OrganizationMembership, PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.temporal.oauth import resolve_scopes

CANARY = "cnry-file-4b2e9d.pdf"


class TestMetadataOnlyAccess(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.metadata_only_key = self._create_key(resolve_scopes("metadata_only", include_internal_scopes=False))
        self.full_key = self._create_key(["*"])
        _create_event(team=self.team, event="uploaded_file", distinct_id="user-1", properties={"file_name": CANARY})
        flush_persons_and_events()

    def _create_key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label=f"key {len(scopes)}", secure_value=hash_key_value(value), scopes=scopes
        )
        return value

    def _call(self, key: str, method: str, path: str, data: dict | None = None):
        self.client.logout()
        if method == "GET":
            return self.client.get(path, HTTP_AUTHORIZATION=f"Bearer {key}")
        return self.client.generic(
            method,
            path,
            data=json.dumps(data or {}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

    @parameterized.expand([("metadata_only_key", "metadata_only"), ("full_key", "full")])
    def test_api_keys_cannot_change_ai_data_access(self, key_attr: str, start: str) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save(update_fields=["level"])
        self.organization.ai_data_access = start
        self.organization.save(update_fields=["ai_data_access"])
        target = "full" if start == "metadata_only" else "metadata_only"

        response = self._call(
            getattr(self, key_attr), "PATCH", f"/api/organizations/{self.organization.id}/", {"ai_data_access": target}
        )

        self.organization.refresh_from_db()
        assert response.status_code == 400, response.content
        assert self.organization.ai_data_access == start

    def test_metadata_only_preset_carries_the_marker(self) -> None:
        assert METADATA_ONLY_SCOPE in resolve_scopes("metadata_only")

    @parameterized.expand(
        [
            ("persons", "GET", "/api/environments/{team}/persons/"),
            ("events", "GET", "/api/environments/{team}/events/"),
            ("recordings", "GET", "/api/environments/{team}/session_recordings/"),
            ("query_log", "GET", "/api/environments/{team}/query/missing-id/"),
        ]
    )
    def test_data_routes_are_blocked(self, _name: str, method: str, path: str) -> None:
        response = self._call(self.metadata_only_key, method, path.format(team=self.team.pk))

        assert response.status_code == 403, response.content
        assert response.json()["code"] == "metadata_only"

    def test_query_compiles_without_returning_rows(self) -> None:
        body = {"query": {"kind": "HogQLQuery", "query": "select properties.file_name from events"}}
        path = f"/api/environments/{self.team.pk}/query/"

        metadata_only = self._call(self.metadata_only_key, "POST", path, body)
        full = self._call(self.full_key, "POST", path, body)

        assert metadata_only.status_code == 200, metadata_only.content
        assert metadata_only.json()["results"] == []
        assert CANARY not in metadata_only.content.decode()
        assert CANARY in full.content.decode()

    def test_query_with_unknown_field_is_rejected(self) -> None:
        body = {"query": {"kind": "HogQLQuery", "query": "select no_such_field from events"}}

        response = self._call(self.metadata_only_key, "POST", f"/api/environments/{self.team.pk}/query/", body)

        assert response.status_code == 400, response.content

    def test_insight_result_is_removed_from_write_and_read_responses(self) -> None:
        body = {
            "name": "Uploads by file",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "uploaded_file"}],
                    "breakdownFilter": {"breakdown": "file_name", "breakdown_type": "event"},
                },
            },
        }
        created = self._call(self.metadata_only_key, "POST", f"/api/environments/{self.team.pk}/insights/", body)
        path = f"/api/environments/{self.team.pk}/insights/{created.json()['id']}/?refresh=blocking"

        metadata_only = self._call(self.metadata_only_key, "GET", path)
        full = self._call(self.full_key, "GET", path)

        assert created.status_code == 201, created.content
        assert metadata_only.status_code == 200, metadata_only.content
        assert full.status_code == 200, full.content
        assert "result" not in created.json()
        assert "result" not in metadata_only.json()
        assert CANARY not in metadata_only.content.decode()
        assert CANARY in full.content.decode()

    @parameterized.expand(
        [
            ("valid", "select properties.file_name from events", 200),
            ("unknown_field", "select no_such_field from events", 400),
        ]
    )
    def test_mcp_execute_sql_only_compiles(self, _name: str, sql: str, expected_status: int) -> None:
        response = self._call(
            self.metadata_only_key,
            "POST",
            f"/api/environments/{self.team.pk}/mcp_tools/execute_sql/",
            {"args": {"query": sql}},
        )

        assert response.status_code == expected_status, response.content
        assert CANARY not in response.content.decode()
