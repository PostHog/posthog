import json
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.baseten import (
    BasetenResumeConfig,
    _flatten_row,
    baseten_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.settings import (
    BASETEN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.baseten.baseten"


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _drive(endpoint: str, manager: MagicMock, responses: list[Response]) -> tuple[list[list[dict]], list[dict]]:
    """Run ``get_rows`` against a mocked HTTP session; return (yielded batches, captured get kwargs)."""
    captured: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_get(url: str, **kwargs: Any) -> Response:
        captured.append({"url": url, "params": kwargs.get("params")})
        return next(response_iter)

    with patch(f"{MODULE}.make_tracked_session") as mock_factory:
        session = mock_factory.return_value
        session.get.side_effect = fake_get
        batches = list(get_rows("test-key", endpoint, MagicMock(), manager))
    return batches, captured


class TestFlattenRow:
    def test_lifts_nested_object_into_root(self) -> None:
        row = _flatten_row({"instance_type": {"id": "gpu-1", "name": "A100"}, "price": 0.5}, "instance_type")
        assert row == {"id": "gpu-1", "name": "A100", "price": 0.5}

    def test_root_keys_win_on_collision(self) -> None:
        # A sibling `price` (or any root key) must survive a nested key of the same name.
        row = _flatten_row({"instance_type": {"id": "gpu-1", "price": 999}, "price": 0.5}, "instance_type")
        assert row["price"] == 0.5

    def test_noop_without_flatten_key(self) -> None:
        row = _flatten_row({"id": "1"}, None)
        assert row == {"id": "1"}

    def test_noop_when_key_absent(self) -> None:
        row = _flatten_row({"id": "1"}, "instance_type")
        assert row == {"id": "1"}


class TestTopLevelEndpoints:
    def test_yields_rows_under_data_key(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        batches, captured = _drive("models", manager, [_response({"models": [{"id": "m1"}, {"id": "m2"}]})])
        assert batches == [[{"id": "m1"}, {"id": "m2"}]]
        assert captured[0]["url"].endswith("/v1/models")

    def test_empty_array_yields_nothing(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        batches, _ = _drive("models", manager, [_response({"models": []})])
        assert batches == []

    def test_instance_type_prices_flattened(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        body = {"instance_types": [{"instance_type": {"id": "gpu-1", "name": "A100"}, "price": 0.5}]}
        batches, _ = _drive("instance_type_prices", manager, [_response(body)])
        assert batches == [[{"id": "gpu-1", "name": "A100", "price": 0.5}]]


class TestCursorPagination:
    def test_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [
            _response({"items": [{"user_id": "u1"}], "pagination": {"has_more": True, "cursor": "c1"}}),
            _response({"items": [{"user_id": "u2"}], "pagination": {"has_more": True, "cursor": "c2"}}),
            _response({"items": [{"user_id": "u3"}], "pagination": {"has_more": False, "cursor": None}}),
        ]
        batches, captured = _drive("users", manager, responses)

        assert batches == [[{"user_id": "u1"}], [{"user_id": "u2"}], [{"user_id": "u3"}]]
        # First request has no cursor; later requests carry the prior page's cursor.
        assert [p["params"].get("cursor") for p in captured] == [None, "c1", "c2"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [BasetenResumeConfig(cursor="c1"), BasetenResumeConfig(cursor="c2")]

    def test_single_terminal_page_does_not_save(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        _drive("users", manager, [_response({"items": [{"user_id": "u1"}], "pagination": {"has_more": False}})])
        manager.save_state.assert_not_called()

    def test_resume_seeds_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BasetenResumeConfig(cursor="resumed-cursor")
        _, captured = _drive("users", manager, [_response({"items": [{"user_id": "u9"}], "pagination": {}})])
        assert captured[0]["params"].get("cursor") == "resumed-cursor"

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        _drive("users", manager, [_response({"items": [], "pagination": {}})])
        manager.load_state.assert_not_called()


class TestFanOut:
    def test_injects_parent_id_and_yields_per_parent(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [
            _response({"models": [{"id": "m1"}, {"id": "m2"}]}),  # parent list
            _response({"deployments": [{"id": "d1"}]}),  # m1 children
            _response({"deployments": [{"id": "d2"}]}),  # m2 children
        ]
        batches, captured = _drive("deployments", manager, responses)

        assert batches == [[{"id": "d1", "model_id": "m1"}], [{"id": "d2", "model_id": "m2"}]]
        assert captured[1]["url"].endswith("/v1/models/m1/deployments")
        assert captured[2]["url"].endswith("/v1/models/m2/deployments")
        # Bookmark advances to the next parent after finishing the first one.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [BasetenResumeConfig(parent_id="m2")]

    def test_composite_key_column_present_for_environments(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [
            _response({"models": [{"id": "m1"}]}),
            _response({"environments": [{"name": "production"}]}),
        ]
        batches, _ = _drive("model_environments", manager, responses)
        # model_id is injected so [model_id, name] stays unique table-wide.
        assert batches == [[{"name": "production", "model_id": "m1"}]]

    def test_404_child_is_skipped(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [
            _response({"models": [{"id": "gone"}, {"id": "m2"}]}),
            _response({"code": "NOT_FOUND"}, status_code=404),  # parent deleted mid-sync
            _response({"deployments": [{"id": "d2"}]}),
        ]
        batches, _ = _drive("deployments", manager, responses)
        assert batches == [[{"id": "d2", "model_id": "m2"}]]

    def test_parent_without_id_is_skipped(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [
            _response({"models": [{"id": "m1"}, {"name": "orphan"}]}),  # second parent has no id
            _response({"deployments": [{"id": "d1"}]}),  # only m1's children are fetched
        ]
        batches, captured = _drive("deployments", manager, responses)
        assert batches == [[{"id": "d1", "model_id": "m1"}]]
        # The id-less parent must not produce a request against a stringified "None" id.
        assert not any("/models/None/" in c["url"] for c in captured)

    def test_resume_starts_from_bookmarked_parent(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BasetenResumeConfig(parent_id="m2")
        responses = [
            _response({"models": [{"id": "m1"}, {"id": "m2"}]}),
            _response({"deployments": [{"id": "d2"}]}),  # only m2 is fetched
        ]
        batches, captured = _drive("deployments", manager, responses)
        assert batches == [[{"id": "d2", "model_id": "m2"}]]
        child_urls = [c["url"] for c in captured if "/deployments" in c["url"]]
        assert child_urls == ["https://api.baseten.co/v1/models/m2/deployments"]


class TestValidateCredentials:
    @pytest.mark.parametrize(("status", "expected"), [(200, True), (403, False), (401, False), (500, False)])
    def test_status_maps_to_bool(self, status: int, expected: bool) -> None:
        with patch(f"{MODULE}.make_tracked_session") as mock_factory:
            session = mock_factory.return_value
            session.get.return_value = _response({}, status_code=status)
            assert validate_credentials("key") is expected

    def test_network_error_is_false(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as mock_factory:
            mock_factory.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") is False


class TestSourceResponseShape:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_partition_and_primary_keys_match_config(self, endpoint: str) -> None:
        config = BASETEN_ENDPOINTS[endpoint]
        response = baseten_source("k", endpoint, MagicMock(), MagicMock(spec=ResumableSourceManager))

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_items_is_lazy(self) -> None:
        # Building the SourceResponse must not perform any I/O; items is a deferred callable.
        response = baseten_source("k", "models", MagicMock(), MagicMock(spec=ResumableSourceManager))
        assert callable(response.items)
        assert isinstance(response.items(), Iterator)
