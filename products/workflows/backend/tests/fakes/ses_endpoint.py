import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from unittest.mock import patch

import boto3
from botocore.awsrequest import AWSPreparedRequest, AWSResponse
from botocore.compat import HTTPHeaders

from posthog.dataclasses import frozen

REPUTATION_ENTITY_PATH = "/v2/email/reputation/entities/RESOURCE/"
METRICS_BATCH_PATH = "/v2/email/metrics/batch"
METRICS_BATCH_MAX_QUERIES = 10
SECONDS_PER_DAY = 24 * 60 * 60


@frozen
class SesRequest:
    method: str
    host: str
    path: str
    body: bytes


@frozen
class _Reply:
    status: int
    body: dict[str, Any]
    error_type: str | None = None


class _RawBody:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def stream(self, **_kwargs: Any) -> Iterator[bytes]:
        yield self._body


class FakeSesEndpoint:
    def __init__(self) -> None:
        self.requests: list[SesRequest] = []
        self.tenants: dict[str, dict[str, str]] = {}
        self.reputation_aggregates: dict[str, str] = {}
        # Account-wide VDM totals per metric, answered for queries that carry no dimension.
        self.account_metrics: dict[str, int] = {}
        self.failing_metrics: set[str] = set()
        self.rejects_metric_batches = False
        self.denied = False

    @contextmanager
    def installed(self) -> Iterator["FakeSesEndpoint"]:
        session = boto3.session.Session()
        session.events.register("before-send", cast(Callable[..., None], self._answer))
        with patch.object(boto3, "DEFAULT_SESSION", session):
            yield self

    def add_tenant(self, name: str, *, sending_status: str, arn: str | None = None) -> None:
        self.tenants[name] = {
            "TenantName": name,
            "SendingStatus": sending_status,
            **({"TenantArn": arn} if arn else {}),
        }

    def _answer(self, request: AWSPreparedRequest, **_kwargs: Any) -> AWSResponse:
        url = urlsplit(request.url)
        body = _body_bytes(request.body)
        self.requests.append(SesRequest(method=request.method, host=url.netloc, path=url.path, body=body))
        reply = self._reply(request.method, url.path, body)
        headers = HTTPHeaders()
        headers["Content-Type"] = "application/json"
        if reply.error_type:
            headers["x-amzn-ErrorType"] = reply.error_type
        return AWSResponse(request.url, reply.status, headers, _RawBody(json.dumps(reply.body).encode()))

    def _reply(self, method: str, path: str, body: bytes) -> _Reply:
        if self.denied:
            return _Reply(status=403, body={"message": "Access denied"}, error_type="AccessDeniedException")
        if (method, path) == ("POST", "/v2/email/tenants/get"):
            tenant = self.tenants.get(json.loads(body)["TenantName"])
            return _Reply(status=200, body={"Tenant": tenant}) if tenant else _not_found("Tenant")
        if method == "GET" and path.startswith(REPUTATION_ENTITY_PATH):
            aggregate = self.reputation_aggregates.get(unquote(path.removeprefix(REPUTATION_ENTITY_PATH)))
            if aggregate is None:
                return _not_found("Reputation entity")
            return _Reply(status=200, body={"ReputationEntity": {"SendingStatusAggregate": aggregate}})
        if (method, path) == ("POST", METRICS_BATCH_PATH):
            return self._metrics_batch(json.loads(body)["Queries"])
        return _bad_request(f"FakeSesEndpoint does not serve {method} {path}")

    def _metrics_batch(self, queries: list[dict[str, Any]]) -> _Reply:
        if self.rejects_metric_batches:
            return _bad_request("Virtual Deliverability Manager is not enabled for this account")
        if len(queries) > METRICS_BATCH_MAX_QUERIES:
            return _bad_request(f"At most {METRICS_BATCH_MAX_QUERIES} queries per request")
        if any(query["Namespace"] != "VDM" for query in queries):
            return _bad_request("Namespace must be VDM")
        if any(query[bound] % SECONDS_PER_DAY for query in queries for bound in ("StartDate", "EndDate")):
            return _bad_request("StartDate and EndDate must be whole UTC days")
        return _Reply(
            status=200,
            body={
                "Results": [
                    {
                        "Id": query["Id"],
                        "Timestamps": [query["StartDate"]],
                        "Values": [0 if query.get("Dimensions") else self.account_metrics.get(query["Metric"], 0)],
                    }
                    for query in queries
                    if query["Metric"] not in self.failing_metrics
                ],
                "Errors": [
                    {"Id": query["Id"], "Code": "INTERNAL_FAILURE", "Message": "Internal failure"}
                    for query in queries
                    if query["Metric"] in self.failing_metrics
                ],
            },
        )


def _bad_request(message: str) -> _Reply:
    return _Reply(status=400, body={"message": message}, error_type="BadRequestException")


def _not_found(resource: str) -> _Reply:
    return _Reply(status=404, body={"message": f"{resource} not found"}, error_type="NotFoundException")


def _body_bytes(body: Any) -> bytes:
    if isinstance(body, bytes | bytearray):
        return bytes(body)
    return body.encode() if isinstance(body, str) else b""
