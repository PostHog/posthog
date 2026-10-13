import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.cloudinary import (
    CloudinaryResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.source import CloudinarySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudinary import (
    CloudinarySourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        CloudinarySource(),
        CloudinarySourceConfig(cloud_name="my-cloud", api_key="key", api_secret="secret", region="global"),
    )


class TestCloudinarySource:
    def test_the_key_and_secret_ride_basic_auth(self) -> None:
        result = _driver().run("images", [ScriptedResponse(json={"resources": [{"asset_id": "one"}]})])

        assert result.raised is None
        assert result.requests[0].headers["authorization"] == "Basic a2V5OnNlY3JldA=="

    def test_a_saved_cursor_seeds_the_paginator(self) -> None:
        result = _driver().run(
            "images",
            [ScriptedResponse(json={"resources": [{"asset_id": "two"}]})],
            resume_state=CloudinaryResumeConfig(cursor="page-2"),
        )

        assert result.raised is None
        assert result.params("next_cursor") == ["page-2"]

    def test_only_a_real_cursor_is_checkpointed(self) -> None:
        without_cursor = _driver().run("images", [ScriptedResponse(json={"resources": [{"asset_id": "one"}]})])
        with_cursor = _driver().run(
            "images",
            [
                ScriptedResponse(json={"resources": [{"asset_id": "one"}], "next_cursor": "next"}),
                ScriptedResponse(json={"resources": [{"asset_id": "two"}]}),
            ],
        )

        assert without_cursor.raised is None
        assert without_cursor.saved_states == []
        assert with_cursor.raised is None
        assert with_cursor.params("next_cursor") == [None, "next"]
        assert with_cursor.saved_states == [CloudinaryResumeConfig(cursor="next")]


class TestCloudinaryCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (401, False), (403, False), (404, False), (420, False), (429, False), (500, False)],
    )
    def test_status_maps_to_a_verdict(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, message = validate_credentials("my-cloud", "key", "secret", "global")

        assert valid is expected_valid
        assert (message is None) is expected_valid
        assert network.requests_log

    def test_the_probe_costs_nothing_against_the_quota(self) -> None:
        # /ping is the one Admin API call Cloudinary does not bill to the hourly limit.
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("my-cloud", "key", "secret", "eu")

        assert network.requests_log[0].url == "https://api-eu.cloudinary.com/v1_1/my-cloud/ping"
        assert network.requests_log[0].headers["authorization"] == "Basic a2V5OnNlY3JldA=="

    def test_an_unreachable_api_is_reported_rather_than_raised(self) -> None:
        with scripted_network(always(ConnectionError("no route"))) as network:
            valid, message = validate_credentials("my-cloud", "key", "secret", "global")

        assert valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/v1_1/my-cloud/ping"}
