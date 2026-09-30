import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.fintoc.source import FintocSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fintoc import FintocSourceConfig


@pytest.mark.parametrize(
    "status,schema,valid,message",
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "customers", False, "permissions"),
        (401, "accounts", False, "invalid or expired"),
    ],
)
def test_credential_probe_distinguishes_scope_from_invalid_key(
    http_mock: MagicMock,
    status: int,
    schema: str | None,
    valid: bool,
    message: str | None,
) -> None:
    http_mock.return_value = (status, [] if status == 200 else {"error": {"code": "invalid_api_key"}}, {})
    result, error = FintocSource().validate_credentials(
        FintocSourceConfig(api_key="sk_test_example", link_tokens="link_example_token"),
        1,
        schema,
    )
    assert result is valid
    if message:
        assert error and message in error
    else:
        assert error is None
    assert http_mock.call_count == 1


@pytest.mark.parametrize(
    "api_key,schema,tokens,message",
    [
        ("bad key", None, None, "without spaces"),
        ("secret\u200b", None, None, "unsupported characters"),
        ("sk_test_example", "missing", None, "Unknown Fintoc table"),
        ("sk_test_example", "accounts", None, "Add link tokens"),
        ("sk_test_example", "movements", None, "Add link tokens"),
    ],
)
def test_bad_configuration_fails_before_http(
    http_mock: MagicMock,
    api_key: str,
    schema: str | None,
    tokens: str | None,
    message: str,
) -> None:
    valid, error = FintocSource().validate_credentials(
        FintocSourceConfig(api_key=api_key, link_tokens=tokens), 1, schema
    )
    assert not valid and error and message in error
    http_mock.assert_not_called()


def test_movements_scope_probe_checks_child_access(http_mock: MagicMock) -> None:
    http_mock.side_effect = [(200, [{"id": "account_example"}], {}), (403, {}, {})]
    valid, message = FintocSource().validate_credentials(
        FintocSourceConfig(api_key="sk_test_example", link_tokens="token_example"),
        1,
        "movements",
    )
    assert not valid and message and "permissions" in message
    assert "/v1/accounts/account_example/movements?" in http_mock.call_args.args[0].url


@pytest.mark.parametrize("tokens,enabled", [(None, False), ("token_one, token_two", True)])
def test_open_banking_default_selection_requires_tokens(tokens: str | None, enabled: bool) -> None:
    schemas = FintocSource().get_schemas(
        FintocSourceConfig(api_key="sk_test_example", link_tokens=tokens), 1, names=["accounts", "links"]
    )
    assert {schema.name: schema.should_sync_default for schema in schemas} == {"accounts": enabled, "links": True}


def test_unknown_pipeline_table_fails_clearly(inputs: MagicMock, manager: MagicMock) -> None:
    inputs.schema_name = "unknown"
    with pytest.raises(ValueError, match="Unknown Fintoc table"):
        FintocSource().source_for_pipeline(FintocSourceConfig(api_key="sk_test_example"), manager, inputs)


@pytest.mark.parametrize("webhook_enabled", [False, True])
def test_pipeline_selects_backfill_or_webhook_rows(
    http_mock: MagicMock,
    inputs: MagicMock,
    manager: MagicMock,
    webhook_enabled: bool,
) -> None:
    inputs.schema_name = "invoices"
    http_mock.return_value = (200, [{"id": "invoice_example"}], {})
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3.WebhookSourceManager.webhook_enabled",
            new=AsyncMock(return_value=webhook_enabled),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3.WebhookSourceManager.get_items",
            return_value=iter([[{"id": "webhook_invoice"}]]),
        ),
    ):
        result = FintocSource().source_for_pipeline(FintocSourceConfig(api_key="sk_test_example"), manager, inputs)
        assert list(result.items()) == [[{"id": "webhook_invoice" if webhook_enabled else "invoice_example"}]]
    assert http_mock.call_count == (0 if webhook_enabled else 1)
    assert result.supports_resume is not webhook_enabled


def test_webhook_creation_persists_secret_and_subscribes_only_routable_events(http_mock: MagicMock) -> None:
    http_mock.side_effect = [(200, [], {}), (201, {"id": "webhook_example", "secret": "whsec_example"}, {})]
    source = FintocSource()
    result = source.create_webhook(FintocSourceConfig(api_key="sk_test_example"), "https://example.com/hook", 1)
    assert result.success and result.extra_inputs == {"signing_secret": "whsec_example"}
    request = http_mock.call_args.args[0]
    payload = json.loads(request.body)
    assert payload["url"] == "https://example.com/hook"
    assert "invoice.upcoming" not in payload["enabled_events"]
    assert all(event.split(".")[0] in source.webhook_resource_map.values() for event in payload["enabled_events"])
    assert request.headers["Fintoc-Version"] == "2026-02-01"
    assert request.headers["Authorization"] == "sk_test_example"


@pytest.mark.parametrize(
    "existing,secret,message",
    [
        (True, "whsec_example", "already exists"),
        (False, None, "did not return a signing secret"),
    ],
)
def test_webhook_creation_does_not_claim_unverifiable_setup(
    http_mock: MagicMock,
    existing: bool,
    secret: str | None,
    message: str,
) -> None:
    url = "https://example.com/hook"
    http_mock.side_effect = [
        (200, [{"id": "webhook_example", "url": url}] if existing else [], {}),
        (201, {"id": "webhook_example", "secret": secret}, {}),
    ]
    result = FintocSource().create_webhook(FintocSourceConfig(api_key="sk_test_example"), url, 1)
    assert not result.success and result.error and message in result.error
    assert http_mock.call_count == (1 if existing else 2)


@pytest.mark.parametrize("exists,delete_status", [(False, 204), (True, 204), (True, 404)])
def test_webhook_delete_matches_url_and_is_idempotent(http_mock: MagicMock, exists: bool, delete_status: int) -> None:
    url = "https://example.com/hook"
    http_mock.side_effect = [
        (
            200,
            [{"id": "unrelated", "url": "https://example.com/other"}],
            {"Link": '<https://api.fintoc.com/v1/webhook_endpoints?page=2>; rel="next"'},
        ),
        (200, [{"id": "matching", "url": url}] if exists else [], {}),
        (delete_status, None, {}),
    ]
    assert FintocSource().delete_webhook(FintocSourceConfig(api_key="sk_test_example"), url, 1).success
    if exists:
        request = http_mock.call_args.args[0]
        assert request.method == "DELETE" and request.url.endswith("/webhook_endpoints/matching")
    else:
        assert http_mock.call_count == 2


@pytest.mark.parametrize("exists", [False, True])
def test_webhook_info_matches_destination(http_mock: MagicMock, exists: bool) -> None:
    url = "https://example.com/hook"
    http_mock.return_value = (
        200,
        [{"url": url, "enabled_events": ["invoice.paid"], "status": "enabled"}] if exists else [],
        {},
    )
    info = FintocSource().get_external_webhook_info(FintocSourceConfig(api_key="sk_test_example"), url, 1)
    assert info.exists is exists
    if exists:
        assert info.url == url and info.enabled_events == ["invoice.paid"] and info.status == "enabled"
