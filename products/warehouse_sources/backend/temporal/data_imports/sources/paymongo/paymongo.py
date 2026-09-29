import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paymongo.settings import (
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    WEBHOOK_EVENTS,
)

if TYPE_CHECKING:
    import pyarrow as pa

    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@frozen
class PaymongoResumeConfig:
    paginator_state: dict[str, Any] | None = None
    finished: bool = False


class PaymongoAuth(HttpBasicAuth):
    def secret_values(self) -> tuple[str, ...]:
        # PayMongo puts the secret in the username; the shared Basic auth redacts the password.
        return (self.username,) if self.username else ()


class PaymongoCursorPaginator(JSONResponseCursorPaginator):
    def __init__(self, cursor_param: str = "after") -> None:
        super().__init__(cursor_path="data[-1].id", cursor_param=cursor_param)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        previous = self._cursor_value
        super().update_state(response, data)
        if response.json().get("has_more") is False:
            self._has_next_page = False
        elif self.has_next_page and self._cursor_value == previous:
            raise ValueError("PayMongo repeated a pagination cursor. The sync cannot continue safely.")


def normalize_row(item: dict[str, Any]) -> dict[str, Any]:
    row = {**item.get("attributes", {}), **{key: value for key, value in item.items() if key != "attributes"}}
    row.pop("secret_key", None)
    for field in ("created_at", "updated_at"):
        if isinstance(row.get(field), int | float):
            row[field] = datetime.fromtimestamp(row[field], tz=UTC)
    return row


def get_resource(name: str) -> EndpointResource:
    settings = schema_for_resource(ENDPOINTS, name)
    endpoint: Endpoint = {"path": settings.path, "data_selector": "data", "data_selector_required": True}
    if settings.pagination == "single":
        # Payment Links documents no cursor; fail instead of silently importing a partial collection.
        endpoint.update(
            paginator="single_page",
            response_actions=[
                {
                    "status_code": 200,
                    "json_field": "has_more",
                    "json_values": [True],
                    "action": "raise",
                    "message": "PayMongo returned more payment links than its documented list API can retrieve.",
                }
            ],
        )
    elif settings.pagination == "payout":
        endpoint.update(
            params={"limit": PAGE_SIZE},
            paginator={"type": "cursor", "cursor_path": "pagination.next_cursor", "cursor_param": "after"},
        )
    else:
        endpoint.update(params={"limit": PAGE_SIZE}, paginator=PaymongoCursorPaginator())
    if name == "refunds":
        endpoint["params"] = {
            "payment_id": {"type": "resolve", "resource": "payments", "field": "id"},
            "data.attributes.limit": PAGE_SIZE,
        }
        endpoint["paginator"] = PaymongoCursorPaginator(cursor_param="data.attributes.after")
    return {"name": name, "endpoint": endpoint, "data_map": normalize_row, "primary_key": list(settings.primary_keys)}


def pull_rows(
    api_key: str, inputs: SourceInputs, manager: ResumableSourceManager[PaymongoResumeConfig]
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    if state and state.finished:
        return

    def save_state(paginator_state: dict[str, Any] | None) -> None:
        manager.save_state(PaymongoResumeConfig(paginator_state=paginator_state, finished=paginator_state is None))

    auth = PaymongoAuth(username=api_key, password="")
    with make_tracked_session(redact_values=auth.secret_values(), capture=inputs.schema_name != "webhooks") as session:
        config: RESTAPIConfig = {
            "client": {"base_url": BASE_URL, "auth": auth, "session": session, "request_timeout": 30},
            "resources": [get_resource(inputs.schema_name)],
        }
        initial_state = state.paginator_state if state else None
        if inputs.schema_name == "refunds":
            config["resources"].insert(0, get_resource("payments"))
            resources = rest_api_resources(
                config,
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=save_state,
                initial_paginator_state=initial_state,
            )
            resource = next(resource for resource in resources if resource.name == "refunds")
        else:
            resource = rest_api_resource(
                config,
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=save_state,
                initial_paginator_state=initial_state,
            )
        yield from resource
    manager.save_state(PaymongoResumeConfig(finished=True))


def webhook_table(table: "pa.Table", client: "PaymongoClient") -> "pa.Table":
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (  # noqa: PLC0415 - keeps Arrow off the source registration path
        table_from_py_list,
    )

    latest: dict[str, dict[str, Any]] = {}
    refunded: set[str] = set()
    for event in table.to_pylist():
        if isinstance(event["data"], str):
            event["data"] = json.loads(event["data"])
        attributes = event["data"]["attributes"]
        item = attributes["data"]
        if item["type"] == "refund":
            payment_id = item["attributes"]["payment_id"]
            refunded.add(payment_id)
        else:
            payment_id = item["id"]
        previous = latest.get(payment_id)
        if previous is None or attributes["created_at"] >= previous["data"]["attributes"]["created_at"]:
            latest[payment_id] = event
    rows = []
    for payment_id, event in latest.items():
        # Refund events can contain only the refund, so retrieve the payment's current snapshot.
        item = (
            client.request("GET", f"payments/{quote(payment_id, safe='')}").json()["data"]
            if payment_id in refunded
            else event["data"]["attributes"]["data"]
        )
        rows.append(normalize_row(item))
    return table_from_py_list(rows)


def paymongo_source(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[PaymongoResumeConfig],
    webhook_manager: WebhookSourceManager,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)

    async def items() -> AsyncIterator[Any]:
        if inputs.schema_name == "payments" and await webhook_manager.webhook_enabled():
            async for table in webhook_manager.get_items(
                table_transformer=lambda table: webhook_table(table, PaymongoClient(api_key))
            ):
                yield table
        else:
            for page in pull_rows(api_key, inputs, manager):
                yield page

    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        primary_keys=list(settings.primary_keys),
        partition_keys=[settings.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
        supports_resume=settings.pagination != "single",
    )


class PaymongoClient:
    def __init__(self, api_key: str) -> None:
        self.auth = PaymongoAuth(username=api_key, password="")

    def request(self, method: str, path: str, **kwargs: Any) -> Response:
        with make_tracked_session(redact_values=self.auth.secret_values(), capture=False) as session:
            response = session.request(method, BASE_URL + path, auth=self.auth, timeout=30, **kwargs)
            response.raise_for_status()
            return response

    def validate_credentials(self, schema_name: str | None) -> tuple[bool, str | None]:
        name = schema_name or "payments"
        endpoint = schema_for_resource(ENDPOINTS, name)
        path = "payments" if name == "refunds" else endpoint.path
        try:
            response = self.request("GET", path, params={} if endpoint.pagination == "single" else {"limit": 1})
            if name == "refunds" and response.json()["data"]:
                self.request(
                    "GET",
                    "refunds",
                    params={"data.attributes.payment_id": response.json()["data"][0]["id"], "data.attributes.limit": 1},
                )
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return (
                    False,
                    "PayMongo rejected your secret API key. Check the key in your PayMongo dashboard and reconnect.",
                )
            if status == 403:
                if schema_name is None:
                    return True, None
                return False, "Your PayMongo API key cannot access this table. Check your account permissions."
            raise
        return True, None

    def webhooks(self) -> Iterator[dict[str, Any]]:
        client = RESTClient(base_url=BASE_URL, auth=self.auth, capture=False, request_timeout=30)
        try:
            for page in client.paginate(
                "webhooks",
                params={"limit": PAGE_SIZE},
                paginator=PaymongoCursorPaginator(),
                data_selector="data",
                data_selector_required=True,
            ):
                yield from page
        finally:
            client.session.close()

    def create_webhook(self, webhook_url: str) -> WebhookCreationResult:
        existing = next((item for item in self.webhooks() if item["attributes"]["url"] == webhook_url), None)
        if existing:
            identifier = quote(existing["id"], safe="")
            self.request(
                "PUT", f"webhooks/{identifier}", json={"data": {"attributes": {"events": list(WEBHOOK_EVENTS)}}}
            )
            response = self.request("POST", f"webhooks/{identifier}/enable")
        else:
            response = self.request(
                "POST", "webhooks", json={"data": {"attributes": {"url": webhook_url, "events": list(WEBHOOK_EVENTS)}}}
            )
        secret = response.json()["data"]["attributes"].get("secret_key")
        return WebhookCreationResult(
            success=True,
            extra_inputs={"signing_secret": secret} if secret else {},
            pending_inputs=[] if secret else ["signing_secret"],
        )

    def delete_webhook(self, webhook_url: str) -> WebhookDeletionResult:
        for item in self.webhooks():
            if item["attributes"]["url"] == webhook_url:
                self.request("POST", f"webhooks/{quote(item['id'], safe='')}/disable")
        return WebhookDeletionResult(success=True)

    def get_external_webhook_info(self, webhook_url: str) -> ExternalWebhookInfo:
        for item in self.webhooks():
            attributes = item["attributes"]
            if attributes["url"] == webhook_url:
                return ExternalWebhookInfo(
                    exists=True, url=webhook_url, enabled_events=attributes["events"], status=attributes["status"]
                )
        return ExternalWebhookInfo(exists=False)


def webhook_template() -> "HogFunctionTemplateDC":
    from posthog.cdp.templates.hog_function_template import (  # noqa: PLC0415 - keeps the template dependencies off the source registration path
        HogFunctionTemplateDC,
    )

    return HogFunctionTemplateDC(
        status="alpha",
        free=False,
        type="warehouse_source_webhook",
        id="template-warehouse-source-paymongo",
        name="PayMongo warehouse source webhook",
        description="Receive PayMongo payment updates for the data warehouse",
        icon_url="/static/services/paymongo.png",
        category=["Data warehouse"],
        code_language="hog",
        code="""
if (request.method != 'POST') {
    return {'httpResponse': {'status': 405, 'body': 'Method not allowed'}}
}
if (empty(inputs.signing_secret)) {
    return {'httpResponse': {'status': 200, 'body': 'Signing secret not configured, delivery dropped'}, 'appMetric': 'missing_credential'}
}
let header := request.headers['paymongo-signature']
if (empty(header)) {
    return {'httpResponse': {'status': 401, 'body': 'Missing signature'}}
}
let parts := {}
for (let part in splitByString(',', header)) {
    let pair := splitByString('=', trim(part))
    if (length(pair) == 2) { parts[pair[1]] := pair[2] }
}
let signature := request.body.data.attributes.livemode ? parts.li : parts.te
if (empty(parts.t) or empty(signature)) {
    return {'httpResponse': {'status': 401, 'body': 'Missing signature'}}
}
let expected := sha256HmacChain([inputs.signing_secret, concat(parts.t, '.', request.stringBody)], 'hex')
if (expected != signature) {
    return {'httpResponse': {'status': 401, 'body': 'Bad signature'}}
}
let age := toInt(toUnixTimestamp(now())) - toInt(parts.t)
if (age > 300 or age < -300) {
    return {'httpResponse': {'status': 401, 'body': 'Timestamp outside tolerance'}}
}
let attributes := request.body.data.attributes
if (not (attributes.data.type in ['payment', 'refund']) or not (attributes.type in ['payment.paid', 'payment.failed', 'payment.refunded', 'payment.refund.updated'])) {
    return {'httpResponse': {'status': 200, 'body': 'Event skipped'}}
}
let schemaId := inputs.schema_mapping?.['payment']
if (empty(schemaId)) { return {'httpResponse': {'status': 200, 'body': 'Table not selected'}} }
produceToWarehouseWebhooks(request.body, schemaId)
""",
        inputs_schema=[
            {"type": "string", "key": "signing_secret", "label": "Signing secret", "required": True, "secret": True},
            {
                "type": "json",
                "key": "schema_mapping",
                "label": "Schema mapping",
                "required": True,
                "hidden": True,
                "secret": False,
            },
            {
                "type": "string",
                "key": "source_id",
                "label": "Source ID",
                "required": True,
                "hidden": True,
                "secret": False,
            },
        ],
    )
