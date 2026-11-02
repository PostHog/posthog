from datetime import UTC, datetime, timedelta

import pytest

from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.gcp_cloud_billing import (
    BillingServiceAccountAuth,
    GcpCloudBillingResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.source import (
    GcpCloudBillingSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudbilling import (
    GcpCloudBillingKeyFileConfig,
    GcpCloudBillingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tests.contract_harness import (
    check_extraction,
    start_source,
)


def token_response(token: str = "fake-access-token") -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": token, "expires_in": 3600, "token_type": "Bearer"})


def test_signed_extraction_meets_worker_contract(key_file: GcpCloudBillingKeyFileConfig) -> None:
    source = GcpCloudBillingSource()
    config = GcpCloudBillingSourceConfig(key_file=key_file)
    verdict = check_extraction(
        start_source(source, config), [schema.name for schema in source.get_schemas(config, team_id=1)]
    )
    assert verdict.failed == frozenset()
    assert verdict.requests > 0
    assert verdict.safe_point_exercised


@pytest.mark.parametrize(
    ("schema", "selector", "path"),
    [("billing_accounts", "billingAccounts", "/v1/billingAccounts"), ("services", "services", "/v1/services")],
)
def test_top_level_pagination_and_committed_resume(
    key_file: GcpCloudBillingKeyFileConfig, schema: str, selector: str, path: str
) -> None:
    result = SourceDriver(GcpCloudBillingSource(), GcpCloudBillingSourceConfig(key_file=key_file)).run(
        schema,
        [
            token_response(),
            ScriptedResponse(json={selector: [{"name": "first"}], "nextPageToken": "next-page"}),
            ScriptedResponse(json={"nextPageToken": "after-empty-page"}),
            ScriptedResponse(json={selector: [{"name": "last"}]}),
        ],
    )
    assert result.raised is None
    assert result.rows == [{"name": "first"}, {"name": "last"}]
    assert result.paths == ["/token", path, path, path]
    assert result.params("pageToken") == [None, None, "next-page", "after-empty-page"]
    assert result.committed_states == [
        GcpCloudBillingResumeConfig(paginator_state={"cursor": "next-page"}),
        GcpCloudBillingResumeConfig(paginator_state={"cursor": "after-empty-page"}),
    ]
    assert result.requests[0].url == "https://oauth2.googleapis.com/token"
    assert all(request.headers.get("authorization") == "Bearer fake-access-token" for request in result.requests[1:])


@pytest.mark.parametrize(
    ("schema", "parent_selector", "parent", "selector", "child_path", "parent_field", "child_host"),
    [
        (
            "projects",
            "billingAccounts",
            "billingAccounts",
            "projectBillingInfo",
            "projects",
            "parent_billing_account",
            "cloudbilling.googleapis.com",
        ),
        (
            "sub_accounts",
            "billingAccounts",
            "billingAccounts",
            "billingAccounts",
            "subAccounts",
            "parent_billing_account",
            "cloudbilling.googleapis.com",
        ),
        (
            "budgets",
            "billingAccounts",
            "billingAccounts",
            "budgets",
            "budgets",
            "parent_billing_account",
            "billingbudgets.googleapis.com",
        ),
        ("skus", "services", "services", "skus", "skus", "parent_service", "cloudbilling.googleapis.com"),
    ],
)
def test_fanout_paginates_parents_and_children(
    key_file: GcpCloudBillingKeyFileConfig,
    schema: str,
    parent_selector: str,
    parent: str,
    selector: str,
    child_path: str,
    parent_field: str,
    child_host: str,
) -> None:
    first_parent = f"{parent}/parent-a"
    second_parent = f"{parent}/parent-b"
    child = f"/v1/{first_parent}/{child_path}"
    result = SourceDriver(GcpCloudBillingSource(), GcpCloudBillingSourceConfig(key_file=key_file)).run(
        schema,
        [
            token_response(),
            ScriptedResponse(json={parent_selector: [{"name": first_parent}], "nextPageToken": "parent-next"}),
            ScriptedResponse(
                json={selector: [{"name": "child-a", "nested": {"amount": 2}}], "nextPageToken": "child-next"}
            ),
            ScriptedResponse(json={selector: [{"name": "child-b", "nested": None}]}),
            ScriptedResponse(json={parent_selector: [{"name": second_parent}]}),
            ScriptedResponse(json={}),
        ],
    )
    assert result.raised is None
    assert result.paths == [
        "/token",
        f"/v1/{parent}",
        child,
        child,
        f"/v1/{parent}",
        f"/v1/{second_parent}/{child_path}",
    ]
    assert result.params("pageToken") == [None, None, None, "child-next", "parent-next", None]
    assert result.rows == [
        {"name": "child-a", "nested": {"amount": 2}, parent_field: first_parent},
        {"name": "child-b", "nested": None, parent_field: first_parent},
    ]
    assert result.requests[2].url.startswith(f"https://{child_host}/")
    assert result.committed_states[0].paginator_state == {
        "completed": [],
        "current": child.lstrip("/") if schema != "budgets" else f"https://{child_host}{child}",
        "child_state": {"cursor": "child-next"},
    }


@pytest.mark.parametrize("fanout", [False, True])
def test_resume_starts_after_saved_page(key_file: GcpCloudBillingKeyFileConfig, fanout: bool) -> None:
    state = (
        {
            "completed": ["v1/services/done/skus"],
            "current": "v1/services/current/skus",
            "child_state": {"cursor": "saved-page"},
        }
        if fanout
        else {"cursor": "saved-page"}
    )
    pages = [token_response()]
    if fanout:
        pages.append(ScriptedResponse(json={"services": [{"name": "services/done"}, {"name": "services/current"}]}))
    pages.append(ScriptedResponse(json={"skus" if fanout else "services": [{"name": "last"}]}))
    result = SourceDriver(GcpCloudBillingSource(), GcpCloudBillingSourceConfig(key_file=key_file)).run(
        "skus" if fanout else "services", pages, resume_state=GcpCloudBillingResumeConfig(paginator_state=state)
    )
    assert result.raised is None
    assert result.params("pageToken")[-1] == "saved-page"
    assert len(result.rows) == 1
    assert "/v1/services/done/skus" not in result.paths


def test_auth_refreshes_expired_token_without_retargeting_key(key_file: GcpCloudBillingKeyFileConfig) -> None:
    with scripted_network([token_response("first-token"), token_response("second-token")]) as network:
        auth = BillingServiceAccountAuth(key_file)
        first = auth(Request("GET", "https://cloudbilling.googleapis.com/v1/services").prepare())
        auth.credentials.expiry = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        second = auth(Request("GET", "https://cloudbilling.googleapis.com/v1/services").prepare())
    assert first.headers["Authorization"] == "Bearer first-token"
    assert second.headers["Authorization"] == "Bearer second-token"
    assert [request.url for request in network.requests_log] == ["https://oauth2.googleapis.com/token"] * 2
    assert any(options.get("capture") is False for options in network.session_options)
