from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.ortto import (
    OrttoResumeConfig,
    _base_url,
    _flatten_custom_field,
    get_rows,
    ortto_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.settings import (
    ACCOUNT_BUILTIN_FIELDS,
    ENDPOINTS,
    ORTTO_ENDPOINTS,
    PERSON_BUILTIN_FIELDS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ortto.ortto"


def _make_manager(resume_state: OrttoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


def _contacts_page(
    contacts: list[dict[str, Any]], has_more: bool, next_offset: int = 0, cursor_id: str | None = None
) -> dict[str, Any]:
    return {"contacts": contacts, "has_more": has_more, "next_offset": next_offset, "cursor_id": cursor_id}


class TestBaseUrl:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("global", "https://api.ap3api.com"),
            ("au", "https://api.au.ap3api.com"),
            ("eu", "https://api.eu.ap3api.com"),
            ("unknown", "https://api.ap3api.com"),
        ],
    )
    def test_region_hosts(self, region, expected):
        assert _base_url(region) == expected


class TestFlattenCustomField:
    def test_wrapped_person_field_is_flattened(self):
        entry = {"field": {"id": "str:cm:plan", "name": "Plan"}, "tracked_value": True}
        assert _flatten_custom_field(entry) == {"id": "str:cm:plan", "name": "Plan", "tracked_value": True}

    def test_flat_account_field_passes_through(self):
        entry = {"id": "str:oc:industry", "name": "Industry"}
        assert _flatten_custom_field(entry) == entry


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.post.return_value = response

        assert validate_credentials("global", "key") is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_probes_region_specific_host(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.post.return_value = response

        validate_credentials("eu", "key")

        url = mock_session.return_value.post.call_args.args[0]
        assert url == "https://api.eu.ap3api.com/v1/person/custom-field/get"


class TestGetRowsCursorPagination:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_people_requests_builtin_plus_discovered_custom_fields(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"fields": [{"field": {"id": "str:cm:plan"}, "tracked_value": False}]}),
            _response(_contacts_page([{"id": "p1", "fields": {}}], has_more=False)),
        ]

        batches = list(get_rows("global", "key", "people", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["p1"]
        page_body = mock_session.return_value.post.call_args_list[1].kwargs["json"]
        assert page_body["fields"] == [*PERSON_BUILTIN_FIELDS, "str:cm:plan"]
        assert page_body["limit"] == 500
        assert page_body["offset"] == 0
        assert "cursor_id" not in page_body

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_with_cursor_until_has_more_is_false(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"fields": []}),
            _response(_contacts_page([{"id": "p1"}], has_more=True, next_offset=500, cursor_id="cur-1")),
            _response(_contacts_page([{"id": "p2"}], has_more=False)),
        ]

        manager = _make_manager()
        batches = list(get_rows("global", "key", "people", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["p1", "p2"]
        second_page_body = mock_session.return_value.post.call_args_list[2].kwargs["json"]
        assert second_page_body["offset"] == 500
        assert second_page_body["cursor_id"] == "cur-1"
        # State saved once, after the first page yielded.
        saved = manager.save_state.call_args_list
        assert [(call.args[0].next_offset, call.args[0].cursor_id) for call in saved] == [(500, "cur-1")]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_offset_and_cursor(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"fields": []}),
            _response(_contacts_page([{"id": "p3"}], has_more=False)),
        ]

        manager = _make_manager(OrttoResumeConfig(next_offset=1000, cursor_id="cur-9"))
        list(get_rows("global", "key", "people", mock.MagicMock(), manager))

        page_body = mock_session.return_value.post.call_args_list[1].kwargs["json"]
        assert page_body["offset"] == 1000
        assert page_body["cursor_id"] == "cur-9"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_accounts_use_account_builtin_fields(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"fields": [{"id": "str:oc:industry"}]}),
            _response({"accounts": [{"id": "a1"}], "has_more": False}),
        ]

        batches = list(get_rows("global", "key", "accounts", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["a1"]
        page_body = mock_session.return_value.post.call_args_list[1].kwargs["json"]
        assert page_body["fields"] == [*ACCOUNT_BUILTIN_FIELDS, "str:oc:industry"]


class TestGetRowsOffsetPagination:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_audiences_paginate_by_offset_until_short_page(self, mock_session):
        page_size = ORTTO_ENDPOINTS["audiences"].page_size
        full_page = [{"id": f"aud-{i}"} for i in range(page_size)]
        mock_session.return_value.post.side_effect = [
            _response(full_page),
            _response([{"id": "aud-last"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("global", "key", "audiences", mock.MagicMock(), manager))

        assert [len(batch) for batch in batches] == [page_size, 1]
        second_body = mock_session.return_value.post.call_args_list[1].kwargs["json"]
        assert second_body["offset"] == page_size
        assert "fields" not in second_body
        assert [call.args[0].next_offset for call in manager.save_state.call_args_list] == [page_size]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session):
        mock_session.return_value.post.side_effect = [_response([])]

        assert list(get_rows("global", "key", "audiences", mock.MagicMock(), _make_manager())) == []


class TestGetRowsSingleRequest:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_tags_single_post_returns_all(self, mock_session):
        mock_session.return_value.post.side_effect = [_response([{"id": 1, "name": "VIP"}])]

        manager = _make_manager()
        batches = list(get_rows("global", "key", "tags", mock.MagicMock(), manager))

        assert batches == [[{"id": 1, "name": "VIP"}]]
        assert mock_session.return_value.post.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_person_custom_fields_are_flattened(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"fields": [{"field": {"id": "int:cm:rating", "name": "Rating"}, "tracked_value": False}]}),
        ]

        batches = list(get_rows("global", "key", "person_custom_fields", mock.MagicMock(), _make_manager()))

        assert batches == [[{"id": "int:cm:rating", "name": "Rating", "tracked_value": False}]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_account_custom_fields_pass_through_flat(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"fields": [{"id": "str:oc:industry", "name": "Industry"}]}),
        ]

        batches = list(get_rows("global", "key", "account_custom_fields", mock.MagicMock(), _make_manager()))

        assert batches == [[{"id": "str:oc:industry", "name": "Industry"}]]


class TestOrttoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        response = ortto_source("global", "key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
