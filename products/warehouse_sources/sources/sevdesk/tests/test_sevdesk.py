from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import RESTClientRetryableError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sevdesk import (
    SevdeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.sevdesk import SevdeskResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.source import SevdeskSource


def sync_items(response: SourceResponse) -> Iterable[Any]:
    items = response.items()
    assert isinstance(items, Iterable)
    return items


@pytest.mark.parametrize("last_page_size", [0, 1])
def test_pagination_checkpoints_after_yield_and_resumes_at_next_page(
    last_page_size: int,
    inputs: SourceInputs,
    source_config: SevdeskSourceConfig,
    http: MagicMock,
    response: Callable[..., Response],
    redis: MagicMock,
) -> None:
    source = SevdeskSource()
    manager = source.get_resumable_source_manager(inputs)
    rows = [{"id": str(index)} for index in range(PAGE_SIZE)]
    http.side_effect = [response({"objects": rows}), RuntimeError("interrupted")]
    iterator = iter(sync_items(source.source_for_pipeline(source_config, manager, inputs)))
    assert next(iterator) == rows
    manager.confirm()
    assert not manager.has_staged_state()
    with pytest.raises(RuntimeError, match="interrupted"):
        next(iterator)
    manager.confirm()
    manager.commit()
    assert manager.load_state() == SevdeskResumeConfig(offset=PAGE_SIZE)

    last_page = [{"id": str(PAGE_SIZE)}] * last_page_size
    http.reset_mock(side_effect=True)
    http.return_value = response({"objects": last_page})
    resumed_manager = source.get_resumable_source_manager(inputs)
    result = source.source_for_pipeline(source_config, resumed_manager, inputs)
    assert list(sync_items(result)) == ([last_page] if last_page else [])
    request = http.call_args.args[0]
    assert parse_qs(urlsplit(request.url).query)["offset"] == [str(PAGE_SIZE)]
    http.assert_called_once()
    resumed_manager.confirm()
    resumed_manager.commit()
    assert resumed_manager.load_state() == SevdeskResumeConfig(completed=True)
    http.reset_mock()
    assert (
        list(sync_items(source.source_for_pipeline(source_config, source.get_resumable_source_manager(inputs), inputs)))
        == []
    )
    http.assert_not_called()


@pytest.mark.parametrize("body", [{}, {"objects": None}, {"objects": {"id": "42"}}])
def test_malformed_success_does_not_replace_table_with_empty_data(
    body: object,
    inputs: SourceInputs,
    source_config: SevdeskSourceConfig,
    http: MagicMock,
    response: Callable[..., Response],
    redis: MagicMock,
) -> None:
    http.return_value = response(body)
    source = SevdeskSource()
    manager = source.get_resumable_source_manager(inputs)
    with patch("time.sleep"), pytest.raises(RESTClientRetryableError):
        list(sync_items(source.source_for_pipeline(source_config, manager, inputs)))
    manager.confirm()
    assert not manager.has_staged_state()


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_are_terminal(
    status: int,
    inputs: SourceInputs,
    source_config: SevdeskSourceConfig,
    http: MagicMock,
    response: Callable[..., Response],
    redis: MagicMock,
) -> None:
    http.return_value = response({"error": "unauthorized"}, status)
    source = SevdeskSource()
    manager = source.get_resumable_source_manager(inputs)
    with pytest.raises(HTTPError) as error:
        list(sync_items(source.source_for_pipeline(source_config, manager, inputs)))
    assert any(pattern in str(error.value) for pattern in source.get_non_retryable_errors())
    manager.confirm()
    assert not manager.has_staged_state()
    http.assert_called_once()


def test_unknown_endpoint_never_sends_credentials(
    inputs: SourceInputs, source_config: SevdeskSourceConfig, http: MagicMock
) -> None:
    inputs.schema_name = "https://example.com/Invoice"
    source = SevdeskSource()
    with pytest.raises(UnknownResourceError):
        source.source_for_pipeline(source_config, source.get_resumable_source_manager(inputs), inputs)
    http.assert_not_called()
