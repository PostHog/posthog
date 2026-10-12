import json
from collections.abc import Iterable
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import ConnectionError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kisi import KisiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.kisi import KisiResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.settings import (
    AUTH_ERROR,
    OFFSET_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.source import KisiSource


def response(rows: list[dict[str, object]], status: int = 200, collection_range: str | None = None) -> Response:
    result = Response()
    result.status_code = status
    result.url = "https://api.kisi.io/locks"
    result._content = json.dumps(rows).encode()
    result.headers["Content-Type"] = "application/json"
    if collection_range is not None:
        result.headers["X-Collection-Range"] = collection_range
    return result


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="locks",
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="test-job",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.mark.parametrize("start_offset", [None, 100])
@pytest.mark.parametrize("last_page_size", [0, 1, 100])
@pytest.mark.parametrize("use_header", [False, True])
def test_pagination_and_resume(
    start_offset: int | None,
    last_page_size: int,
    use_header: bool,
    inputs: SourceInputs,
    manager: MagicMock,
) -> None:
    offset = start_offset or 0
    manager.can_resume.return_value = start_offset is not None
    manager.load_state.return_value = KisiResumeConfig(offset=offset)
    first_page: list[dict[str, object]] = [{"id": offset + i} for i in range(100)]
    last_page: list[dict[str, object]] = [{"id": offset + 100 + i} for i in range(last_page_size)]
    total = offset + 100 + last_page_size
    pages = [
        response(first_page, collection_range=f"{offset}-{offset + 99}/{total}" if use_header else None),
        response(last_page, collection_range=f"{offset + 100}-{offset + 199}/{total}" if use_header else None),
        response([]),
    ]
    with patch("requests.Session.send", side_effect=pages) as send:
        result = KisiSource().source_for_pipeline(KisiSourceConfig(api_key="test-key"), manager, inputs)
        batches = list(cast(Iterable[list[dict[str, object]]], result.items()))
    assert [row for batch in batches for row in batch] == first_page + last_page
    expected_offsets = [offset]
    if not use_header or last_page_size:
        expected_offsets.append(offset + 100)
    if not use_header and last_page_size == 100:
        expected_offsets.append(offset + 200)
    assert [parse_qs(urlsplit(call.args[0].url).query)["offset"] for call in send.call_args_list] == [
        [str(value)] for value in expected_offsets
    ]
    assert [call.args[0].offset for call in manager.save_state.call_args_list] == expected_offsets[1:]


@pytest.mark.parametrize("total,should_fail", [(20_100, False), (20_101, True)])
def test_offset_limit_does_not_silently_truncate(
    total: int, should_fail: bool, inputs: SourceInputs, manager: MagicMock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = KisiResumeConfig(offset=20_000)
    rows: list[dict[str, object]] = [{"id": 20_000 + i} for i in range(100)]
    with patch("requests.Session.send", return_value=response(rows, collection_range=f"20000-20099/{total}")) as send:
        result = KisiSource().source_for_pipeline(KisiSourceConfig(api_key="test-key"), manager, inputs)
        if should_fail:
            with pytest.raises(ValueError, match="pagination limit"):
                list(cast(Iterable[object], result.items()))
            assert OFFSET_ERROR in KisiSource().get_non_retryable_errors()
        else:
            assert list(cast(Iterable[object], result.items())) == [rows]
    send.assert_called_once()


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_auth_errors(status: int, message: str, inputs: SourceInputs, manager: MagicMock) -> None:
    with patch("requests.Session.send", return_value=response([], status)) as send:
        result = KisiSource().source_for_pipeline(KisiSourceConfig(api_key="test-key"), manager, inputs)
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[object], result.items()))
    assert message in [
        text for pattern, text in KisiSource().get_non_retryable_errors().items() if pattern in str(error.value)
    ]
    send.assert_called_once()


@pytest.mark.parametrize(
    "status,message",
    [
        (200, None),
        (401, AUTH_ERROR),
        (403, PERMISSION_ERROR),
        (500, "Kisi could not validate the API key. Try again later."),
        (302, "Kisi returned an unexpected response. Try again later."),
    ],
)
def test_validate_credentials(status: int, message: str | None) -> None:
    with patch("requests.Session.send", return_value=response([], status)) as send:
        assert KisiSource().validate_credentials(KisiSourceConfig(api_key="test-key"), 1) == (status == 200, message)
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.url == "https://api.kisi.io/user"
    assert request.headers["Authorization"] == "KISI-LOGIN test-key"
    assert send.call_args.kwargs["allow_redirects"] is False


def test_validate_connection_error() -> None:
    with patch("requests.Session.send", side_effect=ConnectionError("private detail")):
        assert KisiSource().validate_credentials(KisiSourceConfig(api_key="test-key"), 1) == (
            False,
            "Could not connect to Kisi. Try again later.",
        )


def test_unsupported_table(inputs: SourceInputs, manager: MagicMock) -> None:
    inputs.schema_name = "events"
    with pytest.raises(ValueError, match="Unsupported Kisi table"):
        KisiSource().source_for_pipeline(KisiSourceConfig(api_key="test-key"), manager, inputs)
