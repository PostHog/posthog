from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy import (
    octopus_deploy as octopus_deploy_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.octopus_deploy import (
    OctopusDeployResumeConfig,
    _build_params,
    _format_incremental_value,
    _parse_retry_after,
    get_rows,
    normalize_host,
    octopus_deploy_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.settings import (
    OCTOPUS_DEPLOY_ENDPOINTS,
)


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = {}
    return response


def _page(items: list[dict[str, Any]], has_next: bool) -> mock.MagicMock:
    links = {"Self": "/api/x"}
    if has_next:
        links["Page.Next"] = "/api/x?skip=next"
    return _response(json_data={"Items": items, "Links": links})


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("my-org.octopus.app", "my-org.octopus.app"),
            ("https://my-org.octopus.app", "my-org.octopus.app"),
            ("http://octopus.example.com/", "octopus.example.com"),
            ("  my-org.octopus.app  ", "my-org.octopus.app"),
            ("https://my-org.octopus.app/app#/Spaces-1", "my-org.octopus.app"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildParams:
    def test_tasks_incremental_sends_from_completed_date(self):
        params = _build_params(
            OCTOPUS_DEPLOY_ENDPOINTS["tasks"],
            skip=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert params["fromCompletedDate"] == "2024-01-01T00:00:00+00:00"
        assert params["skip"] == 0
        assert params["take"] == 100

    def test_events_incremental_sends_from(self):
        params = _build_params(
            OCTOPUS_DEPLOY_ENDPOINTS["events"],
            skip=200,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert params["from"] == "2024-01-01T00:00:00+00:00"
        assert params["skip"] == 200

    def test_no_watermark_sends_no_filter(self):
        params = _build_params(
            OCTOPUS_DEPLOY_ENDPOINTS["tasks"],
            skip=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert "fromCompletedDate" not in params

    def test_full_refresh_ignores_stray_watermark(self):
        params = _build_params(
            OCTOPUS_DEPLOY_ENDPOINTS["tasks"],
            skip=0,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert "fromCompletedDate" not in params

    def test_non_incremental_endpoint_never_sends_filter(self):
        # Deployments expose no server-side date filter; an incremental run must not invent one.
        params = _build_params(
            OCTOPUS_DEPLOY_ENDPOINTS["deployments"],
            skip=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert params == {"skip": 0, "take": 100}


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(octopus_deploy_module, "make_tracked_session", return_value=session)

    def test_success(self):
        with self._patch_session(_response(status_code=200, json_data={"Items": []})):
            assert validate_credentials("my-org.octopus.app", "API-KEY") == (True, None)

    def test_invalid_key(self):
        with self._patch_session(_response(status_code=401)):
            valid, msg = validate_credentials("my-org.octopus.app", "API-KEY")
            assert valid is False
            assert msg == "Invalid Octopus Deploy API key"

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(_response(status_code=403)):
            assert validate_credentials("my-org.octopus.app", "API-KEY", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(_response(status_code=403)):
            valid, msg = validate_credentials("my-org.octopus.app", "API-KEY", schema_name="deployments")
            assert valid is False
            assert msg is not None

    def test_error_body_message_is_surfaced(self):
        with self._patch_session(_response(status_code=400, json_data={"ErrorMessage": "Something broke"})):
            valid, msg = validate_credentials("my-org.octopus.app", "API-KEY")
            assert valid is False
            assert msg == "Something broke"

    @pytest.mark.parametrize("bad_host", ["", "not a host!", "https://"])
    def test_invalid_host_short_circuits(self, bad_host):
        valid, msg = validate_credentials(bad_host, "API-KEY")
        assert valid is False
        assert msg == "Invalid Octopus Deploy host"

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("my-org.octopus.app", "API-KEY")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials("my-org.octopus.app", "API-KEY")
            assert valid is False
            assert msg == octopus_deploy_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        # When a team_id is supplied, a host resolving to an internal address is rejected before
        # any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(octopus_deploy_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("10.0.0.1", "API-KEY", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()


class TestOctopusDeploySourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key",
        [
            ("spaces", ["Id"], None),
            ("projects", ["SpaceId", "Id"], None),
            ("releases", ["SpaceId", "Id"], "Assembled"),
            ("deployments", ["SpaceId", "Id"], "Created"),
            ("tasks", ["SpaceId", "Id"], "QueueTime"),
            ("events", ["SpaceId", "Id"], "Occurred"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        response = octopus_deploy_source(
            host="my-org.octopus.app",
            api_key="API-KEY",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "desc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def _run(
        self,
        manager,
        responses,
        endpoint: str = "projects",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Optional[Any] = None,
    ):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with mock.patch.object(octopus_deploy_module, "make_tracked_session", return_value=session):
            rows: list[dict[str, Any]] = []
            for batch in get_rows(
                host="my-org.octopus.app",
                api_key="API-KEY",
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ):
                rows.extend(batch)
        return rows, session

    def _manager(self, resume: Optional[OctopusDeployResumeConfig] = None):
        manager = mock.MagicMock()
        manager.can_resume.return_value = resume is not None
        manager.load_state.return_value = resume
        return manager

    def _requested_urls(self, session):
        return [call.args[0] for call in session.get.call_args_list]

    def test_fans_out_over_spaces_and_stamps_space_id(self):
        manager = self._manager()
        responses = [
            # Spaces enumeration returns unsorted ids; fan-out must be deterministic (sorted).
            _page([{"Id": "Spaces-2"}, {"Id": "Spaces-1"}], has_next=False),
            _page([{"Id": "Projects-1"}], has_next=False),  # Spaces-1
            _page([{"Id": "Projects-1"}], has_next=False),  # Spaces-2
        ]
        rows, session = self._run(manager, responses)

        assert [(r["SpaceId"], r["Id"]) for r in rows] == [("Spaces-1", "Projects-1"), ("Spaces-2", "Projects-1")]
        urls = self._requested_urls(session)
        assert "/api/spaces" in urls[0]
        assert "/api/Spaces-1/projects" in urls[1]
        assert "/api/Spaces-2/projects" in urls[2]

    def test_paginates_with_skip_until_no_next_page(self):
        manager = self._manager()
        responses = [
            _page([{"Id": "Spaces-1"}], has_next=False),
            _page([{"Id": "Projects-1"}, {"Id": "Projects-2"}], has_next=True),
            _page([{"Id": "Projects-3"}], has_next=False),
        ]
        rows, session = self._run(manager, responses)

        assert [r["Id"] for r in rows] == ["Projects-1", "Projects-2", "Projects-3"]
        second_page_qs = parse_qs(urlparse(self._requested_urls(session)[2]).query)
        assert second_page_qs["skip"] == ["2"]

    def test_empty_page_terminates(self):
        manager = self._manager()
        responses = [
            _page([{"Id": "Spaces-1"}], has_next=False),
            _page([], has_next=False),
        ]
        rows, session = self._run(manager, responses)
        assert rows == []
        assert session.get.call_count == 2

    def test_saves_state_after_page_and_between_spaces(self):
        manager = self._manager()
        responses = [
            _page([{"Id": "Spaces-1"}, {"Id": "Spaces-2"}], has_next=False),
            _page([{"Id": "P-1"}], has_next=True),  # Spaces-1 page 1
            _page([{"Id": "P-2"}], has_next=False),  # Spaces-1 page 2
            _page([{"Id": "P-3"}], has_next=False),  # Spaces-2
        ]
        self._run(manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert OctopusDeployResumeConfig(skip=1, space_id="Spaces-1") in saved
        assert OctopusDeployResumeConfig(skip=0, space_id="Spaces-2") in saved

    def test_resumes_from_saved_space_and_skip(self):
        manager = self._manager(OctopusDeployResumeConfig(skip=200, space_id="Spaces-2"))
        responses = [
            _page([{"Id": "Spaces-1"}, {"Id": "Spaces-2"}, {"Id": "Spaces-3"}], has_next=False),
            _page([{"Id": "P-1"}], has_next=False),  # Spaces-2, resumed at skip=200
            _page([{"Id": "P-2"}], has_next=False),  # Spaces-3, fresh at skip=0
        ]
        rows, session = self._run(manager, responses)

        urls = self._requested_urls(session)
        assert "/api/Spaces-2/projects" in urls[1]
        assert parse_qs(urlparse(urls[1]).query)["skip"] == ["200"]
        assert "/api/Spaces-3/projects" in urls[2]
        assert parse_qs(urlparse(urls[2]).query)["skip"] == ["0"]
        # Spaces-1 was already completed before the crash — not re-fetched.
        assert not any("/api/Spaces-1/projects" in url for url in urls)

    def test_resume_bookmark_for_deleted_space_starts_over(self):
        manager = self._manager(OctopusDeployResumeConfig(skip=100, space_id="Spaces-gone"))
        responses = [
            _page([{"Id": "Spaces-1"}], has_next=False),
            _page([{"Id": "P-1"}], has_next=False),
        ]
        rows, session = self._run(manager, responses)

        urls = self._requested_urls(session)
        assert "/api/Spaces-1/projects" in urls[1]
        assert parse_qs(urlparse(urls[1]).query)["skip"] == ["0"]
        assert [r["Id"] for r in rows] == ["P-1"]

    def test_instance_level_endpoint_skips_space_fan_out(self):
        manager = self._manager()
        responses = [_page([{"Id": "Spaces-1"}, {"Id": "Spaces-2"}], has_next=False)]
        rows, session = self._run(manager, responses, endpoint="spaces")

        assert session.get.call_count == 1
        assert [r["Id"] for r in rows] == ["Spaces-1", "Spaces-2"]

    def test_incremental_filter_applied_to_every_page(self):
        manager = self._manager()
        responses = [
            _page([{"Id": "Spaces-1"}], has_next=False),
            _page([{"Id": "T-1"}], has_next=True),
            _page([{"Id": "T-2"}], has_next=False),
        ]
        _rows, session = self._run(
            manager,
            responses,
            endpoint="tasks",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        for url in self._requested_urls(session)[1:]:
            assert parse_qs(urlparse(url).query)["fromCompletedDate"] == ["2024-01-01T00:00:00+00:00"]

    def test_redirect_response_raises(self):
        # Requests are made with allow_redirects=False, and a redirect response is rejected rather
        # than followed to a (potentially internal) Location (SSRF).
        manager = self._manager()
        with pytest.raises(octopus_deploy_module.OctopusDeployHostNotAllowedError):
            self._run(manager, [_response(status_code=302)])

    def test_unsafe_host_raises_before_any_request(self):
        manager = self._manager()
        session = mock.MagicMock()
        with (
            mock.patch.object(octopus_deploy_module, "_is_host_safe", return_value=(False, "internal address")),
            mock.patch.object(octopus_deploy_module, "make_tracked_session", return_value=session),
        ):
            with pytest.raises(octopus_deploy_module.OctopusDeployHostNotAllowedError):
                list(
                    get_rows(
                        host="10.0.0.1",
                        api_key="API-KEY",
                        endpoint="projects",
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                        team_id=1,
                    )
                )
        session.get.assert_not_called()


class TestRetryAfter:
    @pytest.mark.parametrize(
        "headers, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "100000"}, 60.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, headers, expected):
        response = mock.MagicMock()
        response.headers = headers
        assert _parse_retry_after(response) == expected
