from datetime import date
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.cloudinary import (
    CloudinaryResumeConfig,
    usage_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.source import CloudinarySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
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


class TestCloudinarySubfolders:
    def test_the_walk_reaches_every_depth_and_skips_the_root_folders(self) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            pages = {
                ("/v1_1/my-cloud/folders", None): {"folders": [{"path": "shop"}]},
                ("/v1_1/my-cloud/folders/shop", None): {"folders": [{"path": "shop/red shoes"}], "next_cursor": "p2"},
                ("/v1_1/my-cloud/folders/shop", "p2"): {"folders": [{"path": "shop/hats"}]},
                ("/v1_1/my-cloud/folders/shop/red%20shoes", None): {"folders": [{"path": "shop/red shoes/2026"}]},
            }
            return ScriptedResponse(json=pages.get((request.path, request.param("next_cursor")), {"folders": []}))

        result = _driver().run("subfolders", answer)

        assert result.raised is None
        assert [row["path"] for row in result.rows] == ["shop/red shoes", "shop/hats", "shop/red shoes/2026"]
        assert len(result.requests) == 6
        assert result.saved_states[:2] == [
            CloudinaryResumeConfig(cursor="p2", pending_folders=["shop", "shop/red shoes"]),
            CloudinaryResumeConfig(cursor="", pending_folders=["shop/red shoes", "shop/hats"]),
        ]

    def test_a_resume_continues_the_saved_folder_without_relisting_the_root(self) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            pages: dict[tuple[str, str | None], dict[str, Any]] = {
                ("/v1_1/my-cloud/folders/shop", "p2"): {"folders": [{"path": "shop/hats"}]},
            }
            return ScriptedResponse(json=pages.get((request.path, request.param("next_cursor")), {"folders": []}))

        result = _driver().run(
            "subfolders",
            answer,
            resume_state=CloudinaryResumeConfig(cursor="p2", pending_folders=["shop", "shop/red shoes"]),
        )

        assert result.raised is None
        assert [row["path"] for row in result.rows] == ["shop/hats"]
        assert result.paths == [
            "/v1_1/my-cloud/folders/shop",
            "/v1_1/my-cloud/folders/shop/red%20shoes",
            "/v1_1/my-cloud/folders/shop/hats",
        ]


class TestCloudinaryLastAccessReports:
    @staticmethod
    def _answer(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/v1_1/my-cloud/resources_last_access_reports":
            return ScriptedResponse(
                json={
                    "reports": [
                        {"id": "r1", "status": "done"},
                        {"id": "r2", "status": "processing"},
                        {"id": "r3", "status": "done"},
                    ]
                }
            )
        pages = {
            ("r1", None): {"resources": [{"asset_id": "a"}], "next_cursor": "c2"},
            ("r1", "c2"): {"resources": [{"asset_id": "b"}]},
            ("r3", None): {"resources": [{"asset_id": "a"}]},
        }
        report_id = request.path.rsplit("/", 1)[-1]
        return ScriptedResponse(json=pages[(report_id, request.param("next_cursor"))])

    def test_each_completed_report_is_read_and_tagged_with_its_id(self) -> None:
        result = _driver().run("last_access_report_resources", self._answer)

        assert result.raised is None
        assert [(row["report_id"], row["asset_id"]) for row in result.rows] == [("r1", "a"), ("r1", "b"), ("r3", "a")]
        assert result.saved_states == [
            CloudinaryResumeConfig(cursor="c2", report_id="r1"),
            CloudinaryResumeConfig(cursor="", report_id="r3"),
        ]

    def test_a_resume_continues_inside_the_saved_report(self) -> None:
        result = _driver().run(
            "last_access_report_resources",
            self._answer,
            resume_state=CloudinaryResumeConfig(cursor="c2", report_id="r1"),
        )

        assert result.raised is None
        assert [(row["report_id"], row["asset_id"]) for row in result.rows] == [("r1", "b"), ("r3", "a")]


class TestCloudinaryUsage:
    @pytest.mark.parametrize(
        "incremental,watermark,expected",
        [
            (False, None, date(2026, 7, 21)),
            (True, None, date(2026, 7, 21)),
            (True, "2026-10-10", date(2026, 10, 8)),
            (True, date(2026, 10, 10), date(2026, 10, 8)),
            (True, "2025-01-01", date(2026, 7, 21)),
            (False, "2026-10-10", date(2026, 7, 21)),
        ],
    )
    def test_start_date_stays_inside_the_window_cloudinary_answers_for(
        self, incremental: bool, watermark: object, expected: date
    ) -> None:
        assert usage_start_date(incremental, watermark, date(2026, 10, 18)) == expected

    @time_machine.travel("2026-10-18T12:00:00Z", tick=False)
    def test_each_day_is_requested_once_and_keyed_by_its_date(self) -> None:
        result = _driver().run(
            "usage",
            always(ScriptedResponse(json={"plan": "Plus", "storage": {"usage": 1}})),
            resume_state=CloudinaryResumeConfig(cursor="2026-10-17"),
        )

        assert result.raised is None
        assert result.paths == ["/v1_1/my-cloud/usage/2026-10-17", "/v1_1/my-cloud/usage/2026-10-18"]
        assert [(row["date"], row["plan"]) for row in result.rows] == [("2026-10-17", "Plus"), ("2026-10-18", "Plus")]
        assert result.saved_states == [
            CloudinaryResumeConfig(cursor="2026-10-18"),
            CloudinaryResumeConfig(cursor="2026-10-19"),
        ]


class TestCloudinaryCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(404, False), (420, False), (429, False)],
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
