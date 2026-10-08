from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.growthbook import (
    GrowthBookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.growthbook.growthbook import (
    GrowthBookResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.growthbook.source import GrowthBookSource


@pytest.mark.parametrize("resume_offset", [None, 100])
def test_pagination_and_resume(
    config: GrowthBookSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    http: responses.RequestsMock,
    resume_offset: int | None,
) -> None:
    manager.can_resume.return_value = resume_offset is not None
    manager.load_state.return_value = GrowthBookResumeConfig(next_offset=resume_offset or 0)
    offset = resume_offset or 0
    url = "https://api.growthbook.io/api/v2/features"
    first = {"id": "flag-one", "dateCreated": "2025-01-01T00:00:00Z", "archived": True}
    last = {"id": "flag-two", "dateCreated": "2025-01-02T00:00:00Z"}
    http.add(responses.GET, url, json={"features": [first], "hasMore": True, "nextOffset": offset + 7})
    http.add(responses.GET, url, json={"features": [last], "hasMore": False, "nextOffset": None})
    result = GrowthBookSource().source_for_pipeline(config, manager, inputs)
    batches = iter(cast(Iterable[Any], result.items()))
    assert next(batches) == [first]
    manager.save_state.assert_not_called()
    assert next(batches) == [last]
    manager.save_state.assert_called_once_with(GrowthBookResumeConfig(next_offset=offset + 7))
    assert list(batches) == []
    assert len(http.calls) == 2
    for call, expected_offset in zip(http.calls, [offset, offset + 7]):
        assert parse_qs(urlsplit(call.request.url).query) == {
            "limit": ["100"],
            "offset": [str(expected_offset)],
            "archived": ["true"],
        }
        assert call.request.headers["Authorization"] == "Bearer secret_test_growthbook"
    assert result.primary_keys == ["id"]
    assert result.partition_keys == ["dateCreated"]
    assert result.sort_mode is None


@pytest.mark.parametrize("empty", [True, False])
def test_empty_collection_or_missing_envelope(
    config: GrowthBookSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    http: responses.RequestsMock,
    empty: bool,
) -> None:
    payload: dict[str, Any] = {"features": [], "nextOffset": None, "hasMore": False} if empty else {"unexpected": []}
    http.add(responses.GET, "https://api.growthbook.io/api/v2/features", json=payload)
    result = GrowthBookSource().source_for_pipeline(config, manager, inputs)
    if empty:
        assert list(cast(Iterable[Any], result.items())) == []
    else:
        with pytest.raises(ValueError, match="matched nothing"):
            list(cast(Iterable[Any], result.items()))
    assert len(http.calls) == 1
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_error_classification(
    config: GrowthBookSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    http: responses.RequestsMock,
    status: int,
) -> None:
    url = "https://api.growthbook.io/api/v2/features"
    http.add(responses.GET, url, status=status, json={"message": "Request failed"}, headers={"Retry-After": "1"})
    source = GrowthBookSource()
    if status in (401, 403):
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], source.source_for_pipeline(config, manager, inputs).items()))
        assert error_message_matches(str(error.value), source.get_non_retryable_errors())
        assert len(http.calls) == 1
    else:
        http.add(responses.GET, url, json={"features": [{"id": "recovered"}], "nextOffset": None})
        with patch.object(cast(Any, RESTClient._send_request).retry, "sleep"):
            assert list(cast(Iterable[Any], source.source_for_pipeline(config, manager, inputs).items())) == [
                [{"id": "recovered"}]
            ]
        assert len(http.calls) == 2


def test_self_hosted_url_and_redirect_rejection(
    inputs: SourceInputs,
    manager: MagicMock,
    http: responses.RequestsMock,
) -> None:
    config = GrowthBookSourceConfig.from_dict(
        {"api_key": "secret_test_growthbook", "base_url": "https://flags.example.com/custom/api/"}
    )
    http.add(
        responses.GET,
        "https://flags.example.com/custom/api/v2/features",
        status=302,
        headers={"Location": "https://other.example.com/api/v2/features"},
    )
    with pytest.raises(ValueError, match="redirect"):
        list(cast(Iterable[Any], GrowthBookSource().source_for_pipeline(config, manager, inputs).items()))
    assert len(http.calls) == 1
