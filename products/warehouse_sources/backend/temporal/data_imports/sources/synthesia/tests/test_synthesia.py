from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.synthesia import (
    SynthesiaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.source import SynthesiaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.synthesia import (
    SynthesiaResumeConfig,
    synthesia_source,
    validate_credentials,
)


def _driver() -> SourceDriver:
    return SourceDriver(SynthesiaSource(), SynthesiaSourceConfig(api_key="fake-api-key"))


def _page(body: dict[str, Any], status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


@pytest.mark.parametrize("endpoint", ["videos", "templates", "webhooks"])
def test_pagination_uses_returned_offset_and_raw_auth(endpoint: str) -> None:
    rows = [{"id": "item-1", "createdAt": 1700000000}, {"id": "item-2", "createdAt": 1700000001}]
    result = _driver().run(
        endpoint,
        [_page({endpoint: [rows[0]], "nextOffset": 37}), _page({endpoint: [rows[1]]})],
    )

    assert result.items == [[rows[0]], [rows[1]]]
    assert len(result.requests) == 2
    for request, offset in zip(result.requests, ["0", "37"], strict=True):
        assert request.read_timeout == 60.0
        assert request.method == "GET"
        assert request.headers["authorization"] == "fake-api-key"
        assert request.origin == "https://api.synthesia.io"
        assert request.path == f"/v2/{endpoint}"
        assert dict(request.query) == {"limit": ("100",), "offset": (offset,)}
    assert result.saved_states == [SynthesiaResumeConfig(next_offset=37)]
    assert result.final_state == SynthesiaResumeConfig(next_offset=37)


def test_completion_clears_the_saved_cursor() -> None:
    with scripted_network([]):
        manager = SynthesiaSource().get_resumable_source_manager(source_inputs("videos"))
        manager.save_state(SynthesiaResumeConfig(next_offset=37))
        manager.confirm()
        manager.commit()
        assert manager.load_state() == SynthesiaResumeConfig(next_offset=37)

        result = synthesia_source("fake-api-key", "v2", "videos", 1, "job", manager)
        assert result.on_complete is not None
        result.on_complete()

        assert manager.load_state() is None


def test_repeated_offset_fails_instead_of_looping() -> None:
    result = _driver().run(
        "videos",
        always(_page({"videos": [{"id": "v"}], "nextOffset": 12})),
        resume_state=SynthesiaResumeConfig(next_offset=12),
    )

    assert isinstance(result.raised, ValueError)
    assert "repeated cursor" in str(result.raised)
    assert result.saved_states == []


def test_webhook_signing_secrets_are_not_imported() -> None:
    row = {"id": "hook-1", "secret": "fake-signing-secret", "url": "https://example.com/hook", "status": "active"}
    result = _driver().run("webhooks", [_page({"webhooks": [row]})])

    assert result.items == [[{"id": "hook-1", "url": "https://example.com/hook", "status": "active"}]]


@pytest.mark.parametrize("status", [404, 429, 500])
def test_credential_status_mapping(status: int) -> None:
    with scripted_network(always(_page({"videos": []}, status))) as network:
        if status in (200, 401, 403):
            valid, message = validate_credentials("fake-api-key", "v2")
            assert valid is (status == 200)
            if status == 200:
                assert message is None
            else:
                assert message is not None and "Legacy (v2)" in message
        else:
            with pytest.raises(HTTPError):
                validate_credentials("fake-api-key", "v2")

    assert {request.path for request in network.requests_log} == {"/v2/videos"}
    if status in (200, 401, 403, 404):
        assert len(network.requests_log) == 1
    for request in network.requests_log:
        assert request.headers["authorization"] == "fake-api-key"
        assert dict(request.query) == {"limit": ("1",)}


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_are_terminal_and_mapped(status: int) -> None:
    body = {"context": "User is not authenticated", "error": "Forbidden"}
    result = _driver().run("videos", [_page(body, status)])

    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    messages = [
        message
        for pattern, message in SynthesiaSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert len(messages) == 1
    assert messages[0] is not None and "Legacy (v2)" in messages[0]


def test_missing_list_fails_instead_of_replacing_table_with_empty_data() -> None:
    result = _driver().run("videos", [_page({"unexpected": []})])

    assert isinstance(result.raised, ValueError)
