"""The SQLV2 data plane: the sandbox's read path to PostHog data.

Token-authed sandbox -> backend endpoints (like the result callback, plain
function views, no session). The sandbox never parses HogQL — it sends the query
text here; parsing, access control, and execution all stay backend-side.

Queries run through the async query manager (the same Celery-backed path insights
and the SQL editor use), so no web worker ever waits on ClickHouse:

- `POST .../data_plane/query/` validates and enqueues, returning 202 {query_id}.
- `GET .../data_plane/query/<query_id>/` returns 202 while the Celery worker is
  still executing, and the rows as an Arrow stream once complete. The kernel's
  background thread polls this — invisible to the user, who already waits on the
  run callback or the page response.

Wired in posthog/urls.py at internal/notebooks/data_plane/query/.
"""

import json
from typing import Any

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse, JsonResponse

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client.execute_async import QueryNotFoundError, enqueue_process_query_task, get_query_status
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team, User

from products.notebooks.backend.models import Notebook
from products.notebooks.backend.sql_v2 import verify_data_plane_token
from products.notebooks.backend.sql_v2_serializers import NotebookSQLV2DataPlaneRequestSerializer

logger = structlog.get_logger(__name__)

ARROW_STREAM_CONTENT_TYPE = "application/vnd.apache.arrow.stream"


def _rows_to_arrow_bytes(
    columns: list[str], rows: list[tuple[Any, ...]], types: list[list[str]] | None = None
) -> bytes:
    import pyarrow as pa  # noqa: PLC0415 — keeps the heavy dep off the urls.py import path

    # Column-by-column with a per-column string fallback: HogQL results can contain
    # values Arrow can't infer (UUIDs, mixed types, tuples) and one odd column must
    # not fail the whole response.
    arrays = []
    for index in range(len(columns)):
        values = [row[index] for row in rows]
        try:
            arrays.append(pa.array(values))
        except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError):
            arrays.append(pa.array([None if value is None else str(value) for value in values], type=pa.string()))
    table = pa.Table.from_arrays(arrays, names=columns)
    # Carry the HogQL/ClickHouse type names alongside the Arrow schema — the FE viz
    # layer needs them (numeric/date axis detection) and Arrow types are lossier.
    if types:
        table = table.replace_schema_metadata({"hogql_types": json.dumps(types)})
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _verify_request_token(request: HttpRequest) -> tuple[str, int, int | None] | JsonResponse:
    authorization = request.headers.get("Authorization", "")
    token = authorization[len("Bearer ") :].strip() if authorization.startswith("Bearer ") else ""
    if not token:
        return JsonResponse({"error": "Missing authorization bearer token"}, status=401)
    try:
        return verify_data_plane_token(token)
    except signing.BadSignature:
        return JsonResponse({"error": "Invalid data-plane token"}, status=401)


@extend_schema(
    tags=["notebooks"],
    request=NotebookSQLV2DataPlaneRequestSerializer,
    responses={
        202: OpenApiResponse(description="Query accepted; poll the status endpoint with the returned query_id"),
        400: OpenApiResponse(description="Invalid request body or HogQL syntax error"),
        401: OpenApiResponse(description="Missing or invalid data-plane token"),
        404: OpenApiResponse(description="Notebook not found"),
    },
    summary="SQLV2 data-plane query",
    description=(
        "Internal endpoint the notebook sandbox POSTs HogQL to. Authenticated with the signed "
        "data-plane token minted at run dispatch (no session). Validates and enqueues the query "
        "for the notebook's team via the async query manager — HogQL access controls apply — "
        "and returns a query_id for the sandbox to poll."
    ),
)
def notebook_sql_v2_data_plane(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    claims = _verify_request_token(request)
    if isinstance(claims, JsonResponse):
        return claims
    notebook_short_id, team_id, user_id = claims

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    serializer = NotebookSQLV2DataPlaneRequestSerializer(data=body)
    if not serializer.is_valid():
        # The error string is what the kernel surfaces to the user, so make it say which field failed.
        detail = "; ".join(
            f"{field}: {' '.join(str(error) for error in errors)}" for field, errors in serializer.errors.items()
        )
        return JsonResponse({"error": f"Invalid request body — {detail}", "detail": serializer.errors}, status=400)
    data = serializer.validated_data

    if not Notebook.objects.filter(team_id=team_id, short_id=notebook_short_id).exists():
        return JsonResponse({"error": "Notebook not found"}, status=404)
    team = Team.objects.get(id=team_id)
    user = User.objects.filter(id=user_id).first() if user_id else None

    try:
        # Validate the user's HogQL up front so syntax errors fail here with a clear
        # message instead of surfacing through the async status.
        parse_select(data["query"])
    except ExposedHogQLError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    # Wrap rather than mutate the user's query: the outer LIMIT/OFFSET caps the page
    # regardless of the query's own shape (set queries, its own LIMIT, etc.).
    # nosemgrep: semgrep.rules.security.hogql-fstring-audit — the inner query is validated HogQL
    # (parsed above) and the wrapper is re-parsed as HogQL downstream, so there is no raw-SQL
    # injection; limit/offset are int()-cast.
    wrapped = f"select * from ({data['query']}) limit {int(data['limit'])} offset {int(data['offset'])}"

    try:
        with tags_context(product=Product.NOTEBOOKS, feature=Feature.QUERY, team_id=team.id):
            status = enqueue_process_query_task(
                team=team,
                user_id=user.id if user else None,
                query_json={"kind": "HogQLQuery", "query": wrapped},
                # Dispatch normally rides transaction.on_commit, which never fires inside
                # a test transaction — run inline there, like the manager's own tests do.
                _test_only_bypass_celery=settings.TEST,
            )
    except Exception:
        logger.exception("notebook_sql_v2_data_plane_enqueue_failed", notebook_short_id=notebook_short_id)
        return JsonResponse({"error": "Query could not be scheduled."}, status=500)

    return JsonResponse({"query_id": status.id}, status=202)


@extend_schema(
    tags=["notebooks"],
    responses={
        (200, ARROW_STREAM_CONTENT_TYPE): OpenApiResponse(description="Query result as an Arrow IPC stream"),
        202: OpenApiResponse(description="Query is still running"),
        400: OpenApiResponse(description="Query failed"),
        401: OpenApiResponse(description="Missing or invalid data-plane token"),
        404: OpenApiResponse(description="Query not found or expired"),
    },
    summary="SQLV2 data-plane query status",
    description=(
        "Internal endpoint the notebook sandbox polls for an enqueued data-plane query. "
        "Returns 202 while the query runs and the rows as an Arrow IPC stream once complete."
    ),
)
def notebook_sql_v2_data_plane_status(request: HttpRequest, query_id: str) -> HttpResponse:
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    claims = _verify_request_token(request)
    if isinstance(claims, JsonResponse):
        return claims
    _notebook_short_id, team_id, _user_id = claims

    try:
        status = get_query_status(team_id=team_id, query_id=query_id)
    except QueryNotFoundError:
        return JsonResponse({"error": "Query not found or expired"}, status=404)

    if not status.complete:
        return JsonResponse({"status": "running"}, status=202)
    if status.error:
        return JsonResponse({"error": status.error_message or "Query execution failed."}, status=400)

    results: dict[str, Any] = status.results or {}
    columns = [str(column) for column in (results.get("columns") or [])]
    types = [[str(name), str(type_name)] for name, type_name in (results.get("types") or [])]
    payload = _rows_to_arrow_bytes(columns, results.get("results") or [], types)
    return HttpResponse(payload, content_type=ARROW_STREAM_CONTENT_TYPE)
