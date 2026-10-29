from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okendo import OkendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.okendo import (
    OkendoResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.settings import (
    OKENDO_API_VERSION,
    REVIEW_STATUSES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.source import OkendoSource


def _reviews_page(ids: list[str], next_cursor: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"reviews": [{"reviewId": review_id} for review_id in ids]}
    if next_cursor is not None:
        body["nextUrl"] = f"/enterprise/reviews?limit=100&lastEvaluated={next_cursor}"
    return ScriptedResponse(json=body)


class TestReviewsTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(OkendoSource(), OkendoSourceConfig(user_id="user-1", api_key="key-1"))

    @parameterized.expand(
        [
            ("no_next_url", None),
            ("next_url_without_cursor", "/enterprise/reviews?limit=100"),
            ("next_url_repeating_the_sent_cursor", "/enterprise/reviews?lastEvaluated=cursor-1"),
        ]
    )
    def test_pagination_terminates(self, _name: str, next_url: str | None) -> None:
        first: dict[str, Any] = {"reviews": [{"reviewId": "a1"}]}
        if next_url is not None:
            first["nextUrl"] = next_url

        # Seeded so the repeated-cursor case sends the cursor the response then echoes back.
        result = self._driver().run(
            "reviews",
            [ScriptedResponse(json=first), _reviews_page(["p1"]), _reviews_page(["r1"])],
            resume_state=OkendoResumeConfig(variant="approved", last_evaluated="cursor-1"),
        )

        # One request per status: the run ends rather than looping on an unusable next link.
        assert result.raised is None
        assert result.params("status") == list(REVIEW_STATUSES)
        assert result.params("lastEvaluated") == ["cursor-1", None, None]
        assert [row["reviewId"] for row in result.rows] == ["a1", "p1", "r1"]

    def test_checkpoints_the_next_page_then_the_next_status(self) -> None:
        result = self._driver().run(
            "reviews",
            [
                _reviews_page(["a1"], next_cursor="cursor-1"),
                _reviews_page(["a2"]),
                _reviews_page(["p1"]),
                _reviews_page(["r1"]),
            ],
        )

        assert result.raised is None
        assert result.params("lastEvaluated") == [None, "cursor-1", None, None]
        assert result.saved_states == [
            OkendoResumeConfig(variant="approved", last_evaluated="cursor-1"),
            OkendoResumeConfig(variant="pending", last_evaluated=None),
            OkendoResumeConfig(variant="rejected", last_evaluated=None),
        ]


class TestEndpointRequests:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(OkendoSource(), OkendoSourceConfig(user_id="user-1", api_key="key-1"))

    @parameterized.expand(
        [
            ("loyalty_earning_rules", "/loyalty/earning_rules"),
            ("loyalty_redemption_rules", "/loyalty/redemption_rules"),
        ]
    )
    def test_rule_catalogs_are_read_as_a_single_page(self, endpoint: str, path: str) -> None:
        # A nextUrl here must be ignored: neither rules endpoint documents limit/lastEvaluated, so
        # replaying a cursor against them would loop on the same page.
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json={"rules": [{"type": "points-per-spend"}], "nextUrl": "/enterprise/x?lastEvaluated=c"}
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [{"type": "points-per-spend"}]
        assert result.paths == [f"/enterprise{path}"]
        assert result.requests[0].param("limit") is None
        assert result.requests[0].param("status") is None

    @parameterized.expand(
        [
            ("reviews", ["reviewId"], ["dateCreated"]),
            ("loyalty_earning_rules", ["type"], None),
            ("loyalty_redemption_rules", ["redemptionRuleId"], None),
        ]
    )
    def test_primary_and_partition_keys(
        self, endpoint: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        # Okendo rows carry no `id`, so a key copied from another source would be null for every
        # row and every merge would multi-match.
        script = (
            [_reviews_page([]) for _ in REVIEW_STATUSES]
            if endpoint == "reviews"
            else [ScriptedResponse(json={"rules": []})]
        )
        result = self._driver().run(endpoint, script)

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == primary_keys
        assert result.response.partition_keys == partition_keys

    def test_unexpected_response_shape_fails_loud(self) -> None:
        result = self._driver().run("reviews", [ScriptedResponse(json={"data": [{"reviewId": "a1"}]})])

        # A renamed row key must not read as "0 rows synced".
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestValidateCredentials:
    @parameterized.expand([("forbidden", 403, False)])
    def test_reports_the_probe_status(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            # The status is returned, not just a bool, so the source can accept 403 at connect time.
            assert validate_credentials("user-1", "key-1", OKENDO_API_VERSION) == (expected, status_code)

        assert [request.path for request in network.requests_log] == ["/enterprise/reviews"]
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["okendo-api-version"] == OKENDO_API_VERSION
