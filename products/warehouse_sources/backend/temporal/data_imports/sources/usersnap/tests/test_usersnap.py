from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import jwt
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.settings import (
    ENDPOINTS,
    USERSNAP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap import (
    JWT_TTL_SECONDS,
    UsersnapResumeConfig,
    _format_datetime,
    get_rows,
    mint_jwt,
    usersnap_source,
    validate_credentials,
)


def _make_manager(resume_state: UsersnapResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _resp(payload: dict[str, Any]) -> mock.MagicMock:
    response = mock.MagicMock(status_code=200, ok=True)
    response.json.return_value = payload
    return response


def _resp_404() -> mock.MagicMock:
    response = mock.MagicMock(status_code=404, ok=False, text="not found")
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


def _projects_page(projects: list[dict[str, Any]], has_more: bool = False) -> dict[str, Any]:
    return {"status": True, "data": {"has_more": has_more, "count": len(projects), "projects": projects}}


def _feedbacks_page(
    items: list[dict[str, Any]], has_more: bool = False, next_after: str | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {"has_more": has_more, "count": len(items), "feedbacks": items}
    if next_after is not None:
        data["next"] = {"after": next_after, "limit": 100}
    return {"status": True, "data": data}


class TestMintJwt:
    def test_token_uses_hs256_with_kid_header_and_expiry(self):
        token = mint_jwt("shared-secret", "jwt-id-123")

        header = jwt.get_unverified_header(token)
        assert header["alg"] == "HS256"
        assert header["kid"] == "jwt-id-123"

        claims = jwt.decode(token, "shared-secret", algorithms=["HS256"])
        assert claims["exp"] - claims["iat"] == JWT_TTL_SECONDS


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            (date(2026, 1, 2), "2026-01-02T00:00:00Z"),
            ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ],
    )
    def test_format_datetime_values(self, value, expected):
        assert _format_datetime(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("secret", "jwt-id") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("secret", "jwt-id") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_projects_yields_single_batch(self, mock_session):
        projects = [{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}]
        mock_session.return_value.request.return_value = _resp(_projects_page(projects))

        batches = list(get_rows("secret", "jwt-id", "projects", mock.MagicMock(), _make_manager()))

        assert batches == [projects]
        assert mock_session.return_value.request.call_count == 1

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_projects_truncation_is_surfaced(self, mock_session):
        mock_session.return_value.request.return_value = _resp(_projects_page([{"project_id": "p1"}], has_more=True))
        logger = mock.MagicMock()

        list(get_rows("secret", "jwt-id", "projects", logger, _make_manager()))

        logger.warning.assert_called_once()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_feedbacks_paginates_with_after_cursor_and_saves_state_after_yield(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}])),
            _resp(_feedbacks_page([{"feedback_id": "f1"}, {"feedback_id": "f2"}], has_more=True, next_after="f2")),
            _resp(_feedbacks_page([{"feedback_id": "f3"}], has_more=False)),
        ]

        manager = _make_manager()
        batches = list(get_rows("secret", "jwt-id", "feedbacks", mock.MagicMock(), manager))

        assert [item["feedback_id"] for batch in batches for item in batch] == ["f1", "f2", "f3"]
        second_page_url = mock_session.return_value.request.call_args_list[2].args[1]
        assert "after=f2" in second_page_url
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == UsersnapResumeConfig(project_id="p1", after="f2")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_feedbacks_falls_back_to_last_item_cursor_when_next_missing(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}])),
            _resp(_feedbacks_page([{"feedback_id": "f1"}], has_more=True)),
            _resp(_feedbacks_page([{"feedback_id": "f2"}], has_more=False)),
        ]

        batches = list(get_rows("secret", "jwt-id", "feedbacks", mock.MagicMock(), _make_manager()))

        assert [item["feedback_id"] for batch in batches for item in batch] == ["f1", "f2"]
        assert "after=f1" in mock_session.return_value.request.call_args_list[2].args[1]

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, expected_query",
        [
            (
                True,
                datetime(2026, 1, 1, tzinfo=UTC),
                [{"filter_type": "created_at", "operator": "gte", "value": "2026-01-01T00:00:00Z"}],
            ),
            (False, None, None),
            (True, None, None),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_feedbacks_filter_body(self, mock_session, should_use_incremental_field, last_value, expected_query):
        mock_session.return_value.request.side_effect = [
            _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}])),
            _resp(_feedbacks_page([{"feedback_id": "f1"}], has_more=False)),
        ]

        list(
            get_rows(
                "secret",
                "jwt-id",
                "feedbacks",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
            )
        )

        body = mock_session.return_value.request.call_args_list[1].kwargs["json"]
        assert body["order_by"] == {"direction": "asc", "order_by_type": "created_at"}
        assert body.get("query") == expected_query

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_feedbacks_fans_out_over_projects_and_bookmarks_the_next_one(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}])),
            _resp(_feedbacks_page([{"feedback_id": "f1"}], has_more=False)),
            _resp(_feedbacks_page([{"feedback_id": "f2"}], has_more=False)),
        ]

        manager = _make_manager()
        batches = list(get_rows("secret", "jwt-id", "feedbacks", mock.MagicMock(), manager))

        assert [item["feedback_id"] for batch in batches for item in batch] == ["f1", "f2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == UsersnapResumeConfig(project_id="p2", after=None)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_feedbacks_resumes_from_bookmarked_project_and_cursor(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}])),
            _resp(_feedbacks_page([{"feedback_id": "f9"}], has_more=False)),
        ]

        manager = _make_manager(UsersnapResumeConfig(project_id="p2", after="f8"))
        batches = list(get_rows("secret", "jwt-id", "feedbacks", mock.MagicMock(), manager))

        assert [item["feedback_id"] for batch in batches for item in batch] == ["f9"]
        resumed_url = mock_session.return_value.request.call_args_list[1].args[1]
        assert "/projects/p2/feedbacks/filter" in resumed_url
        assert "after=f8" in resumed_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_feedbacks_restarts_when_bookmarked_project_no_longer_exists(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}])),
            _resp(_feedbacks_page([{"feedback_id": "f1"}], has_more=False)),
        ]

        manager = _make_manager(UsersnapResumeConfig(project_id="gone", after="f8"))
        batches = list(get_rows("secret", "jwt-id", "feedbacks", mock.MagicMock(), manager))

        assert [item["feedback_id"] for batch in batches for item in batch] == ["f1"]
        assert "after=" not in mock_session.return_value.request.call_args_list[1].args[1]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_feedbacks_skips_project_deleted_mid_sync(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}])),
            _resp_404(),
            _resp(_feedbacks_page([{"feedback_id": "f2"}], has_more=False)),
        ]

        batches = list(get_rows("secret", "jwt-id", "feedbacks", mock.MagicMock(), _make_manager()))

        assert [item["feedback_id"] for batch in batches for item in batch] == ["f2"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.usersnap.make_tracked_session"
    )
    def test_assignees_fan_out_rows_carry_project_id(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _resp(_projects_page([{"project_id": "p1", "api_key": "k1"}, {"project_id": "p2", "api_key": "k2"}])),
            _resp({"status": True, "data": {"users": [{"user_id": "u1"}]}}),
            _resp({"status": True, "data": {"users": [{"user_id": "u1"}, {"user_id": "u2"}]}}),
        ]

        batches = list(get_rows("secret", "jwt-id", "project_assignees", mock.MagicMock(), _make_manager()))

        rows = [row for batch in batches for row in batch]
        assert [(row["project_id"], row["user_id"]) for row in rows] == [("p1", "u1"), ("p2", "u1"), ("p2", "u2")]
        # The assignees endpoint is keyed on the project's api_key, not its project_id.
        assert "/projects/k1/assignees" in mock_session.return_value.request.call_args_list[1].args[1]
        assert "/projects/k2/assignees" in mock_session.return_value.request.call_args_list[2].args[1]


class TestUsersnapSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = USERSNAP_ENDPOINTS[endpoint]
        response = usersnap_source("secret", "jwt-id", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # The feedbacks fan-out concatenates per-project streams, so it must not checkpoint
        # the incremental watermark per batch.
        assert response.sort_mode == ("desc" if endpoint == "feedbacks" else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(USERSNAP_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
