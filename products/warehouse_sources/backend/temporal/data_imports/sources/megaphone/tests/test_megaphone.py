from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.megaphone import (
    MegaphoneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.megaphone.megaphone import MegaphoneResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.megaphone.source import MegaphoneSource

API_TOKEN = "test-megaphone-token"
ORG_ID = "3ea516ea-a2d1-11e6-8e62-83147939747c"
NEXT_URL = f"https://cms.megaphone.fm/api/search/episodes?organizationId={ORG_ID}&page=2&per_page=500"


def _driver(organization_id: str = ORG_ID) -> SourceDriver:
    return SourceDriver(MegaphoneSource(), MegaphoneSourceConfig(api_token=API_TOKEN, organization_id=organization_id))


def _episodes(ids: list[str], next_url: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(json=[{"id": i, "updatedAt": "2026-10-01T10:00:00.000Z"} for i in ids], headers=headers)


class TestMegaphoneEpisodes:
    def test_follows_the_link_header_to_the_last_page(self) -> None:
        result = _driver().run("episodes", [_episodes(["e1", "e2"], next_url=NEXT_URL), _episodes(["e3"])])

        assert result.raised is None
        assert result.urls[1] == NEXT_URL
        assert {r.headers.get("authorization") for r in result.requests} == {f'Token token="{API_TOKEN}"'}
        assert [row["id"] for row in result.rows] == ["e1", "e2", "e3"]
        assert result.committed_states == [MegaphoneResumeConfig(next_url=NEXT_URL)]

    def test_resume_continues_from_the_saved_link(self) -> None:
        result = _driver().run("episodes", [_episodes(["e3"])], resume_state=MegaphoneResumeConfig(next_url=NEXT_URL))

        assert result.urls == [NEXT_URL]

    def test_resume_refuses_a_link_to_another_host(self) -> None:
        result = _driver().run(
            "episodes",
            always(_episodes([])),
            resume_state=MegaphoneResumeConfig(next_url="https://attacker.example.com/api/search/episodes"),
        )

        assert result.raised is not None
        assert all(r.origin == "https://cms.megaphone.fm" for r in result.requests)

    @parameterized.expand(
        [
            (
                "incremental",
                {
                    "incremental_field": "updatedAt",
                    "db_incremental_field_last_value": datetime(2026, 9, 30, 8, 15, tzinfo=UTC),
                },
                "updatedAt",
                "updatedAt",
                "2026-09-30T08:15:00.000Z",
                "desc",
            ),
            ("full_refresh", {}, "pubdate", None, None, "asc"),
        ]
    )
    def test_search_request_shaping(
        self,
        _name: str,
        inputs: dict[str, Any],
        order_by: str,
        filter_by: str | None,
        expected_filter_min: str | None,
        expected_sort: str,
    ) -> None:
        result = _driver().run("episodes", [_episodes(["e1"])], **inputs)

        request = result.requests[0]
        assert request.path == "/api/search/episodes"
        assert request.param("organizationId") == ORG_ID
        assert request.param("orderBy") == order_by
        assert request.param("filterBy") == filter_by
        assert request.param("filterMin") == expected_filter_min
        assert result.response is not None
        assert result.response.sort_mode == expected_sort


class TestMegaphonePodcasts:
    def test_fans_out_over_the_organization_networks(self) -> None:
        result = _driver().run(
            "podcasts",
            route(
                {
                    f"/api/organizations/{ORG_ID}/networks": [ScriptedResponse(json=[{"id": "n1"}, {"id": "n2"}])],
                    "/api/networks/n1/podcasts": [ScriptedResponse(json=[{"id": "p1", "networkId": "n1"}])],
                    "/api/networks/n2/podcasts": [ScriptedResponse(json=[{"id": "p2", "networkId": "n2"}])],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p1", "p2"]
        assert {r.param("per_page") for r in result.requests} == {"500"}

    def test_resume_skips_networks_already_read(self) -> None:
        result = _driver().run(
            "podcasts",
            route(
                {
                    f"/api/organizations/{ORG_ID}/networks": [ScriptedResponse(json=[{"id": "n1"}, {"id": "n2"}])],
                    "/api/networks/n2/podcasts": [ScriptedResponse(json=[{"id": "p2", "networkId": "n2"}])],
                }
            ),
            resume_state=MegaphoneResumeConfig(
                fanout_state={"completed": ["/networks/n1/podcasts"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == [f"/api/organizations/{ORG_ID}/networks", "/api/networks/n2/podcasts"]


class TestMegaphoneValidateCredentials:
    @parameterized.expand(
        [
            ("ok", ORG_ID, 200, True),
            ("bad_token", ORG_ID, 401, False),
            ("other_organization", ORG_ID, 403, False),
            ("path_escape", "../users", 200, False),
        ]
    )
    def test_maps_probe_status(self, _name: str, organization_id: str, status: int, expected_valid: bool) -> None:
        config = MegaphoneSourceConfig(api_token=API_TOKEN, organization_id=organization_id)
        body = {} if status == 200 else {"error": "Not authorized to access this organization"}
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            valid, message = MegaphoneSource().validate_credentials(config, team_id=1)

        assert valid is expected_valid
        assert (message is None) is expected_valid
        if organization_id != ORG_ID:
            assert network.requests_log == []
