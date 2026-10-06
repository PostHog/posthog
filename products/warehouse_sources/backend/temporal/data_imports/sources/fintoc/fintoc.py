import hashlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
    RESTAPIConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fintoc.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    LINK_TOKEN_ERROR,
    PERMISSION_ERROR,
)

if TYPE_CHECKING:
    import pyarrow as pa

    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@frozen
class FintocResumeState:
    paginator: dict[str, Any] | None = None
    complete: bool = False


def parse_link_tokens(value: str | None) -> list[str]:
    return list(dict.fromkeys((value or "").replace(",", " ").split()))


def _without_link_token(state: dict[str, Any]) -> dict[str, Any]:
    result = dict(state)
    if result.get("next_url"):
        parts = urlsplit(result["next_url"])
        query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key != "link_token"])
        result["next_url"] = urlunsplit(parts._replace(query=query))
    if result.get("child_state"):
        result["child_state"] = _without_link_token(result["child_state"])
    return result


class FintocAPI:
    def __init__(self, api_key: str, api_version: str) -> None:
        self.api_key = api_key
        self.api_version = api_version

    def client_config(self, link_token: str | None = None) -> ClientConfig:
        headers = {"Fintoc-Version": self.api_version, "Accept": "application/json"}
        if link_token:
            # Query auth reapplies the token on every page, including sanitized resume URLs.
            headers["Authorization"] = self.api_key
        return {
            "base_url": BASE_URL,
            "headers": headers,
            "auth": {
                "type": "api_key",
                "name": "link_token" if link_token else "Authorization",
                "location": "query" if link_token else "header",
                "api_key": link_token or self.api_key,
            },
            "session": make_tracked_session(redact_values=(self.api_key, link_token or ""), capture=False),
            "paginator": "header_link",
            "allowed_hosts": ["api.fintoc.com"],
            "allow_redirects": False,
            "request_timeout": (10, 60),
        }

    def validate_credentials(self, schema_name: str | None, link_tokens: list[str]) -> tuple[bool, str | None]:
        name = schema_name or "links"
        if name not in ENDPOINTS:
            return False, "Unknown Fintoc table. Select a supported table."
        if ENDPOINTS[name].requires_link_token and not link_tokens:
            return False, LINK_TOKEN_ERROR
        tokens: list[str | None] = list(link_tokens) if ENDPOINTS[name].requires_link_token else [None]
        try:
            for token in tokens:
                # Movements need an account ID, so probe the account before probing its child scope.
                probe_name = "accounts" if name == "movements" else name
                resource = self.resource(probe_name, page_size=1)
                config: RESTAPIConfig = {"client": self.client_config(token), "resources": [resource]}
                page = next(iter(rest_api_resource(config, 0, "fintoc-validation", None)), [])
                if name == "movements" and page:
                    config["resources"] = [self.resource(name, page_size=1, account_id=page[0]["id"])]
                    next(iter(rest_api_resource(config, 0, "fintoc-validation", None)), None)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, AUTH_ERROR
            if status == 403:
                return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
            raise
        return True, None

    @staticmethod
    def resource(name: str, page_size: int = 300, account_id: str | None = None) -> EndpointResource:
        endpoint = ENDPOINTS[name]
        params: dict[str, Any] = {endpoint.page_size_param: page_size}
        path = endpoint.path
        if name == "movements":
            params["confirmed_only"] = "false"
            if account_id is not None:
                path = path.format(account_id=quote(account_id, safe=""))
            else:
                params["account_id"] = {"type": "resolve", "resource": "accounts", "field": "id"}
        resource: EndpointResource = {
            "name": name,
            "endpoint": {"path": path, "params": params, "data_selector": "$"},
        }
        if name == "movements" and account_id is None:
            resource["include_from_parent"] = ["id"]
        return resource

    def rows(
        self,
        name: str,
        link_tokens: list[str],
        inputs: SourceInputs,
        manager: ResumableSourceManager[FintocResumeState],
    ) -> Iterator[list[dict[str, Any]]]:
        endpoint = ENDPOINTS[name]
        if endpoint.requires_link_token and not link_tokens:
            raise ValueError(LINK_TOKEN_ERROR)
        tokens: list[str | None] = list(link_tokens) if endpoint.requires_link_token else [None]
        for token in tokens:
            token_manager = manager.with_namespace(hashlib.sha256(token.encode()).hexdigest()) if token else manager
            resume = token_manager.load_state() if token_manager.can_resume() else None
            if resume and resume.complete:
                continue

            def save_state(
                state: dict[str, Any] | None,
                current_manager: ResumableSourceManager[FintocResumeState] = token_manager,
            ) -> None:
                # Resume state is logged by the manager, so never persist token-bearing next links.
                current_manager.save_state(
                    FintocResumeState(
                        paginator=_without_link_token(state) if state is not None else None,
                        complete=state is None,
                    )
                )

            resource = self.resource(name)
            resources: list[str | EndpointResource] = [resource]
            if name == "movements":
                resources = [self.resource("accounts"), resource]
            config: RESTAPIConfig = {"client": self.client_config(token), "resources": resources}
            result = rest_api_resources(
                config,
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=save_state,
                initial_paginator_state=resume.paginator if resume else None,
            )[-1]
            for page in result:
                if name == "movements":
                    for row in page:
                        row["account_id"] = row.pop("_accounts_id")
                yield page
            token_manager.save_state(FintocResumeState(complete=True))

    def source(
        self,
        name: str,
        link_tokens: list[str],
        inputs: SourceInputs,
        manager: ResumableSourceManager[FintocResumeState],
    ) -> SourceResponse:
        if name not in ENDPOINTS:
            raise ValueError("Unknown Fintoc table. Select a supported table.")
        endpoint = ENDPOINTS[name]
        return SourceResponse(
            name=name,
            items=lambda: self.rows(name, link_tokens, inputs, manager),
            primary_keys=list(endpoint.primary_keys),
            partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
            partition_mode="datetime" if endpoint.partition_key else None,
            partition_format="month" if endpoint.partition_key else None,
            sort_mode="desc",
        )

    def _webhook_request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        with make_tracked_session(
            headers={"Authorization": self.api_key, "Fintoc-Version": self.api_version},
            redact_values=(self.api_key,),
            capture=False,
        ) as session:
            response = session.request(method, f"{BASE_URL}{path}", json=body, timeout=(10, 60), allow_redirects=False)
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("Fintoc returned an unexpected redirect.")
            return response.json() if response.content else None

    def _find_webhook(self, url: str) -> dict[str, Any] | None:
        config: RESTAPIConfig = {
            "client": self.client_config(),
            "resources": [{"name": "webhooks", "endpoint": {"path": "/v1/webhook_endpoints", "data_selector": "$"}}],
        }
        for page in rest_api_resource(config, 0, "fintoc-webhooks", None):
            for webhook in page:
                if webhook["url"] == url:
                    return webhook
        return None

    def create_webhook(self, url: str) -> WebhookCreationResult:
        if self._find_webhook(url):
            return WebhookCreationResult(
                success=False,
                error="This webhook already exists. Enter its signing secret or delete it before creating another.",
            )
        result = self._webhook_request(
            "POST",
            "/v1/webhook_endpoints",
            {
                "url": url,
                "description": "PostHog data warehouse",
                "enabled_events": [event for endpoint in ENDPOINTS.values() for event in endpoint.webhook_events],
            },
        )
        if not result.get("secret"):
            return WebhookCreationResult(
                success=False,
                error="Fintoc did not return a signing secret. Check the webhook in Fintoc before trying again.",
            )
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": result["secret"]})

    def delete_webhook(self, url: str) -> WebhookDeletionResult:
        webhook = self._find_webhook(url)
        if webhook:
            try:
                self._webhook_request("DELETE", f"/v1/webhook_endpoints/{quote(webhook['id'], safe='')}")
            except HTTPError as error:
                if error.response is None or error.response.status_code != 404:
                    raise
        return WebhookDeletionResult(success=True)

    def webhook_info(self, url: str) -> ExternalWebhookInfo:
        webhook = self._find_webhook(url)
        if webhook is None:
            return ExternalWebhookInfo(exists=False)
        return ExternalWebhookInfo(
            exists=True,
            url=webhook["url"],
            enabled_events=webhook["enabled_events"],
            description=webhook.get("description"),
            created_at=webhook.get("created_at"),
            status=webhook.get("status"),
        )


def webhook_table(table: "pa.Table") -> "pa.Table":
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (  # noqa: PLC0415 - keeps Arrow off the source registry import path
        table_from_py_list,
    )

    latest: dict[str, dict[str, Any]] = {}
    for event in table.to_pylist():
        row = event.get("data")
        if not isinstance(row, dict) or not row.get("id"):
            continue
        previous = latest.get(row["id"])
        if previous is None or (event.get("created_at") or "") >= (previous.get("created_at") or ""):
            latest[row["id"]] = event
    return table_from_py_list([event["data"] for event in latest.values()])


def webhook_template() -> "HogFunctionTemplateDC":
    from posthog.cdp.templates.hog_function_template import (  # noqa: PLC0415 - keeps template dependencies off the source registry import path
        HogFunctionTemplateDC,
    )

    return HogFunctionTemplateDC(
        status="alpha",
        free=False,
        type="warehouse_source_webhook",
        id="template-warehouse-source-fintoc",
        name="Fintoc warehouse source webhook",
        description="Receive Fintoc events for data warehouse ingestion",
        icon_url="/static/services/fintoc.png",
        category=["Data warehouse"],
        code_language="hog",
        code="""
if (request.method != 'POST') {
    return {'httpResponse': {'status': 405, 'body': 'Method not allowed'}}
}
if (empty(inputs.signing_secret)) {
    return {'httpResponse': {'status': 503, 'body': 'Signing secret not configured'}}
}
let timestamp := null
let signatures := []
for (let _, part in splitByString(',', request.headers['fintoc-signature'] ?? '')) {
    let pair := splitByString('=', trim(part), 2)
    if (length(pair) = 2) {
        if (pair[1] = 't') { timestamp := pair[2] }
        if (pair[1] = 'v1') { signatures := arrayPushBack(signatures, pair[2]) }
    }
}
if (empty(timestamp) or empty(signatures)) {
    return {'httpResponse': {'status': 400, 'body': 'Invalid signature timestamp'}}
}
if (not match(timestamp, '^[0-9]{1,12}$')) {
    return {'httpResponse': {'status': 400, 'body': 'Invalid signature timestamp'}}
}
let age := toUnixTimestamp(now()) - toInt(timestamp)
if (age > 300 or age < -300) {
    return {'httpResponse': {'status': 400, 'body': 'Invalid signature timestamp'}}
}
let expected := sha256HmacChainHex([inputs.signing_secret, concat(timestamp, '.', request.stringBody)])
if (not has(signatures, expected)) {
    return {'httpResponse': {'status': 400, 'body': 'Invalid signature'}}
}
let schemaId := inputs.schema_mapping?.[request.body.data?.object]
if (not empty(schemaId) and not empty(request.body.data?.id)) {
    produceToWarehouseWebhooks(request.body, schemaId)
}
return {'httpResponse': {'status': 200, 'body': 'OK'}}
""",
        inputs_schema=[
            {"type": "string", "key": "signing_secret", "label": "Signing secret", "required": True, "secret": True},
            {"type": "json", "key": "schema_mapping", "label": "Schema mapping", "required": True, "hidden": True},
            {"type": "string", "key": "source_id", "label": "Source ID", "required": True, "hidden": True},
        ],
    )
