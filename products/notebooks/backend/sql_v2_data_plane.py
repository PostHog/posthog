"""The SQLV2 data plane: the sandbox's read path to PostHog data.

Token-authed sandbox -> backend endpoint (like the result callback, a plain
function view, no session) that runs a HogQL query for the notebook's team and
streams the result back as Arrow. The sandbox never parses HogQL — it sends the
query text here; parsing, access control, and execution all stay backend-side.
Wired in posthog/urls.py at internal/notebooks/data_plane/query/.
"""

import json
from typing import Any

from django.core import signing
from django.http import HttpRequest, HttpResponse, JsonResponse

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

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


@extend_schema(
    tags=["notebooks"],
    request=NotebookSQLV2DataPlaneRequestSerializer,
    responses={
        (200, ARROW_STREAM_CONTENT_TYPE): OpenApiResponse(description="Query result as an Arrow IPC stream"),
        400: OpenApiResponse(description="Invalid request body or HogQL error"),
        401: OpenApiResponse(description="Missing or invalid data-plane token"),
        404: OpenApiResponse(description="Notebook not found"),
    },
    summary="SQLV2 data-plane query",
    description=(
        "Internal endpoint the notebook sandbox POSTs HogQL to. Authenticated with the signed "
        "data-plane token minted at run dispatch (no session). Runs the query for the notebook's "
        "team — HogQL access controls apply — and returns the rows as an Arrow IPC stream."
    ),
)
def notebook_sql_v2_data_plane(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    authorization = request.headers.get("Authorization", "")
    token = authorization[len("Bearer ") :].strip() if authorization.startswith("Bearer ") else ""
    if not token:
        return JsonResponse({"error": "Missing authorization bearer token"}, status=401)

    try:
        notebook_short_id, team_id, user_id = verify_data_plane_token(token)
    except signing.BadSignature:
        return JsonResponse({"error": "Invalid data-plane token"}, status=401)

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
        # Wrap rather than mutate the user's query: the outer LIMIT/OFFSET caps the page
        # regardless of the query's own shape (set queries, its own LIMIT, etc.).
        inner = parse_select(data["query"])
        wrapped = parse_select(
            f"select * from {{__sqlv2_inner__}} limit {int(data['limit'])} offset {int(data['offset'])}",
            placeholders={"__sqlv2_inner__": inner},
        )
        with tags_context(product=Product.NOTEBOOKS, feature=Feature.QUERY, team_id=team.id):
            response = execute_hogql_query(query=wrapped, team=team, query_type="SQLV2DataPlaneQuery", user=user)
    except ExposedHogQLError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        logger.exception("notebook_sql_v2_data_plane_query_failed", notebook_short_id=notebook_short_id)
        return JsonResponse({"error": "Query execution failed."}, status=500)

    columns = [str(column) for column in (response.columns or [])]
    types = [[str(name), str(type_name)] for name, type_name in (response.types or [])]
    payload = _rows_to_arrow_bytes(columns, response.results or [], types)
    return HttpResponse(payload, content_type=ARROW_STREAM_CONTENT_TYPE)
