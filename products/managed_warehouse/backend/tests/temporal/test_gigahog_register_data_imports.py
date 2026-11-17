import re
import json
import uuid
import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any
from urllib.parse import parse_qs

import pytest
from unittest.mock import patch

import pyarrow as pa
import requests
import requests_mock
import pyarrow.parquet as pq
from temporalio.exceptions import ApplicationError

from products.managed_warehouse.backend.temporal import gigahog_client as client_module
from products.managed_warehouse.backend.temporal.gigahog_client import GigahogConfig
from products.managed_warehouse.backend.temporal.gigahog_register_data_imports import (
    gigahog_columns,
    gigahog_landing_uri,
    register_prepared_files_in_gigahog,
)

GIGAHOG_URL = "http://gigahog.test:8080"
TOKEN_URL = "http://hogtower.test/oauth/token"
CATALOG = "imports-dev"
DATA_PATH = "s3://gigahog-bucket/imports/"
ORG = "0F0E0D0C-0B0A-4000-8000-000000000042"
TEAM = 42
TABLE = "stripe_charge"
ATTEMPT = "0123456789abcdef0123456789abcdef"
CONFIG = GigahogConfig(
    url=GIGAHOG_URL,
    catalog=CATALOG,
    data_path=DATA_PATH,
    token_url=TOKEN_URL,
    client_id="hlw_writer",
    client_secret="writer-secret",
)


class _FakeGigahog:
    """hogtower's token endpoint and the hoglake routes the writer calls, held in memory.

    Like the public listener, it refuses requests without a current token and an `author` from a tenant token, keeps
    a receipt per idempotency key, and refuses a changed body under a key it has seen.
    """

    def __init__(self) -> None:
        self.namespaces: dict[str, dict[str, Any] | None] = {}
        self.tables: dict[tuple[str, str], dict[str, Any]] = {}
        self.live_files: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.snapshot = 1
        self.receipts: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self.commits = 0
        self.tokens_issued = 0
        self.valid_token: str | None = None
        self.capabilities = ["atomic-partition-replacement-v1", "org-marked-containment-v1"]
        # Faults the next commit request meets. "lost" commits and drops the response. "conflict" is another
        # writer's commit landing first. "unavailable" refuses without committing. "token_expired" expires the token.
        self.commit_faults: list[str] = []

    def install(self, mocker: requests_mock.Mocker) -> None:
        mocker.post(TOKEN_URL, json=self._token)
        mocker.register_uri(
            requests_mock.ANY, re.compile(re.escape(f"{GIGAHOG_URL}/v1/catalogs/{CATALOG}") + "(/|$)"), json=self
        )

    def mark(self, team_id: int, org: str) -> None:
        self.namespaces[f"team_{team_id}"] = {"field": "team_id", "value": team_id, "org": org}

    def _token(self, request: Any, context: Any) -> Any:
        assert parse_qs(request.body) == {
            "grant_type": ["client_credentials"],
            "client_id": ["hlw_writer"],
            "client_secret": ["writer-secret"],
        }
        self.tokens_issued += 1
        self.valid_token = f"token-{self.tokens_issued}"
        return {"access_token": self.valid_token, "token_type": "Bearer", "expires_in": 900}

    def __call__(self, request: Any, context: Any) -> Any:
        path = request.path.removeprefix(f"/v1/catalogs/{CATALOG}")
        body: dict[str, Any] = json.loads(request.body) if request.body else {}
        if path == "/commit/replacements/prepared" and self.commit_faults[:1] == ["token_expired"]:
            self.commit_faults.pop(0)
            self.valid_token = None
        if request.headers.get("Authorization") != f"Bearer {self.valid_token}":
            context.status_code = 401
            return {"error": "unauthorized"}
        if "author" in body:
            context.status_code = 422
            return {"error": "validation", "detail": "a tenant token cannot claim an author"}
        if request.method == "GET" and path == "":
            return {"name": CATALOG, "capabilities": self.capabilities}
        if match := re.fullmatch(r"/namespaces/([^/]+)/containment", path):
            assert request.method == "PUT"
            if any(namespace == match.group(1) for namespace, _ in self.tables):
                context.status_code = 409
                return {"error": "namespace_not_empty"}
            self.namespaces[match.group(1)] = body
            return body
        if request.method == "POST" and path == "/namespaces":
            if body["name"] in self.namespaces:
                context.status_code = 409
                return {"error": "already_exists"}
            self.namespaces[body["name"]] = None
            context.status_code = 201
            return {"name": body["name"]}
        if match := re.fullmatch(r"/namespaces/([^/]+)", path):
            containment = self.namespaces[match.group(1)]
            return {"name": match.group(1), **({"containment": containment} if containment else {})}
        if match := re.fullmatch(r"/namespaces/([^/]+)/tables", path):
            key = (match.group(1), body["name"])
            if key in self.tables:
                context.status_code = 409
                return {"error": "already_exists"}
            self.tables[key] = {
                "namespace": key[0],
                "name": key[1],
                "table_uuid": str(uuid.uuid4()),
                "columns": body["columns"],
            }
            self.live_files[key] = []
            context.status_code = 201
            return self.tables[key]
        if match := re.fullmatch(r"/namespaces/([^/]+)/tables/([^/]+)", path):
            table = self.tables.get((match.group(1), match.group(2)))
            if table is None:
                context.status_code = 404
                return {"error": "table_not_found"}
            return {**table, "read_snapshot_id": self.snapshot}
        if path == "/commit/replacements/prepared":
            return self._replace(context, body)
        raise AssertionError(f"unexpected {request.method} {path}")

    def _replace(self, context: Any, body: dict[str, Any]) -> Any:
        fault = self.commit_faults.pop(0) if self.commit_faults else None
        if fault == "conflict":
            self.snapshot += 1
        if fault == "unavailable":
            context.status_code = 503
            return {"error": "unavailable"}
        key = body["idempotency_key"]
        if key in self.receipts:
            first_body, receipt = self.receipts[key]
            if first_body != body:
                context.status_code = 422
                return {"error": "idempotency_key_reused"}
            return receipt
        if body["read_snapshot"] != self.snapshot:
            context.status_code = 409
            return {"error": "commit_conflict"}
        (append,) = body["appends"]
        (end,) = body["file_ends"]
        assert end["all_files"] is True
        table_key = (append["namespace"], append["table"])
        assert self.tables[table_key]["table_uuid"] == append["expected_table_uuid"] == end["expected_table_uuid"]
        ended = len(self.live_files[table_key])
        self.live_files[table_key] = append["files"]
        self.snapshot += 1
        self.commits += 1
        self.receipts[key] = (body, {"snapshot_id": self.snapshot, "schema_version": 1, "ended_files": ended})
        if fault == "lost":
            raise requests.ConnectionError("connection reset after the commit")
        return self.receipts[key][1]


class _LocalFiles:
    def __init__(self, root: Path) -> None:
        self.root = root

    def local(self, path: str) -> Path:
        return self.root / path.removeprefix("s3://")

    def open(self, path: str, mode: str = "rb") -> IO[bytes]:
        return self.local(path).open(mode)


@pytest.fixture
def gigahog():
    fake = _FakeGigahog()
    fake.mark(TEAM, ORG.lower())
    with requests_mock.Mocker() as mocker, patch.object(client_module, "_TRANSIENT_BACKOFF_SECONDS", 0):
        fake.install(mocker)
        yield fake


@pytest.fixture
def files(tmp_path):
    return _LocalFiles(tmp_path)


def _landing_uri(generation: str = "1234567890_abcdef12") -> str:
    generation_uri = gigahog_landing_uri(
        DATA_PATH,
        organization_id=ORG,
        team_id=TEAM,
        table_name=TABLE,
        source_schema_id="schema",
        job_id="job",
        generation_token=generation,
    )
    return f"{generation_uri}/{ATTEMPT}/attempt"


def _write_generation(files: _LocalFiles, landing_uri: str, tables: dict[str, pa.Table]) -> list[str]:
    paths = []
    for name, table in tables.items():
        path = f"{landing_uri}/{name}"
        files.local(path).parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, files.local(path))
        paths.append(path)
    return paths


def _charges(*ids: int) -> pa.Table:
    return pa.table({"id": pa.array([str(i) for i in ids]), "amount": pa.array(list(ids), pa.int64())})


def _register(
    files: _LocalFiles,
    landing_uri: str,
    paths: list[str],
    *,
    attempt: str = ATTEMPT,
    hive_partition_columns: tuple[str, ...] = (),
    should_publish: Callable[[], bool] = lambda: True,
    config: GigahogConfig = CONFIG,
):
    return register_prepared_files_in_gigahog(
        config=config,
        organization_id=ORG,
        team_id=TEAM,
        table_name=TABLE,
        attempt_token=attempt,
        landing_uri=landing_uri,
        landing_paths=paths,
        hive_partition_columns=hive_partition_columns,
        filesystem=files,
        should_publish=should_publish,
    )


def test_registration_creates_the_team_table_and_each_sync_replaces_all_its_files(gigahog, files) -> None:
    first_uri = _landing_uri("1000000000_aaaaaaaa")
    first = _write_generation(files, first_uri, {"a.parquet": _charges(1, 2), "b.parquet": _charges(3)})

    assert _register(files, first_uri, first).row_count == 3

    assert first_uri.startswith(f"s3://gigahog-bucket/imports/org_id={ORG.lower()}/team_id=42/stripe_charge/")
    assert gigahog.tables[("team_42", TABLE)]["columns"] == [
        {"name": "id", "type": "string", "nullable": True},
        {"name": "amount", "type": "long", "nullable": True},
    ]
    assert [(file["path"], file["record_count"]) for file in gigahog.live_files[("team_42", TABLE)]] == [
        (first[0], 2),
        (first[1], 1),
    ]
    assert all(
        file["file_size_bytes"] == files.local(file["path"]).stat().st_size
        for file in gigahog.live_files[("team_42", TABLE)]
    )

    second_uri = _landing_uri("2000000000_bbbbbbbb")
    second = _write_generation(files, second_uri, {"a.parquet": _charges(4)})
    assert _register(files, second_uri, second, attempt=uuid.uuid4().hex).row_count == 1

    assert [file["path"] for file in gigahog.live_files[("team_42", TABLE)]] == second


@pytest.mark.parametrize("fault", ["lost", "conflict", "unavailable", "token_expired"])
def test_a_repeated_commit_lands_the_generation_once(gigahog, files, fault: str) -> None:
    gigahog.commit_faults = [fault]
    landing_uri = _landing_uri()
    paths = _write_generation(files, landing_uri, {"a.parquet": _charges(1, 2)})

    assert _register(files, landing_uri, paths).published

    assert gigahog.commits == 1
    assert [file["path"] for file in gigahog.live_files[("team_42", TABLE)]] == paths


@pytest.mark.parametrize(
    "case, retryable",
    [
        ("outside_team_prefix", False),
        ("data_in_hive_partition", False),
        ("changed_columns", False),
        ("unsupported_type", False),
        ("case_only_names", False),
        ("columns_with_field_ids", False),
        # A table in an unmarked namespace would keep it from ever being marked, so the run waits for the mark.
        ("namespace_without_org_mark", True),
        ("namespace_of_another_org", False),
    ],
)
def test_registration_refuses_without_committing(gigahog, files, case, retryable) -> None:
    landing_uri = _landing_uri()
    tables = {"a.parquet": _charges(1)}
    hive_partition_columns: tuple[str, ...] = ()
    if case == "outside_team_prefix":
        landing_uri = landing_uri.replace("team_id=42", "team_id=43")
    elif case == "data_in_hive_partition":
        hive_partition_columns = ("_ph_partition_key", "region")
    elif case == "namespace_without_org_mark":
        del gigahog.namespaces["team_42"]
    elif case == "namespace_of_another_org":
        gigahog.mark(TEAM, str(uuid.UUID(int=1)))
    elif case == "changed_columns":
        gigahog.tables[("team_42", TABLE)] = {
            "namespace": "team_42",
            "name": TABLE,
            "table_uuid": str(uuid.uuid4()),
            "columns": [{"name": "id", "type": "string", "nullable": True}],
        }
        gigahog.live_files[("team_42", TABLE)] = [{"path": "old"}]
    elif case == "unsupported_type":
        tables = {"a.parquet": pa.table({"tags": pa.array([["a"]], pa.list_(pa.string()))})}
    elif case == "columns_with_field_ids":
        field = pa.field("id", pa.string(), metadata={b"PARQUET:field_id": b"7"})
        tables = {"a.parquet": pa.table({"id": ["1"]}, schema=pa.schema([field]))}
    elif case == "case_only_names":
        tables = {"a.parquet": pa.table({"id": ["1"]}), "b.parquet": pa.table({"ID": ["2"]})}
    paths = _write_generation(files, landing_uri, tables)

    with pytest.raises(ApplicationError) as raised:
        _register(files, landing_uri, paths, hive_partition_columns=hive_partition_columns)

    assert raised.value.non_retryable is not retryable
    assert gigahog.commits == 0
    if case.startswith("namespace_"):
        assert gigahog.tables == {}
    if case == "changed_columns":
        assert gigahog.live_files[("team_42", TABLE)] == [{"path": "old"}]


@pytest.mark.parametrize("server_can_mark", [True, False])
def test_an_enabled_writer_marks_a_new_namespace_before_its_first_table(gigahog, files, server_can_mark) -> None:
    del gigahog.namespaces["team_42"]
    if not server_can_mark:
        # An older server would confine the namespace to `data/team_42/` and refuse every import file.
        gigahog.capabilities.remove("org-marked-containment-v1")
    landing_uri = _landing_uri()
    paths = _write_generation(files, landing_uri, {"a.parquet": _charges(1)})
    config = dataclasses.replace(CONFIG, mark_namespaces=True)

    if server_can_mark:
        assert _register(files, landing_uri, paths, config=config).published
        assert gigahog.namespaces["team_42"] == {"field": "team_id", "value": 42, "org": ORG.lower()}
        assert gigahog.commits == 1
        return
    with pytest.raises(ApplicationError) as raised:
        _register(files, landing_uri, paths, config=config)
    assert raised.value.non_retryable is False
    assert gigahog.namespaces["team_42"] is None
    assert gigahog.tables == {}


def test_a_stale_generation_creates_no_table(gigahog, files) -> None:
    landing_uri = _landing_uri()
    paths = _write_generation(files, landing_uri, {"a.parquet": _charges(1)})

    assert _register(files, landing_uri, paths, should_publish=lambda: False).published is False
    assert gigahog.tables == {}
    assert gigahog.commits == 0


@pytest.mark.parametrize(
    "arrow_type, expected",
    [
        (pa.timestamp("us", tz="UTC"), ("timestamptz", None)),
        (pa.timestamp("ms"), ("timestamp_ms", None)),
        (pa.decimal128(12, 2), ("decimal", {"precision": 12, "scale": 2})),
        (pa.large_string(), ("string", None)),
        (pa.timestamp("ns", tz="UTC"), None),
        (pa.decimal256(50, 2), None),
        (pa.uint32(), None),
    ],
)
def test_gigahog_columns_map_only_types_that_keep_their_values(arrow_type: pa.DataType, expected: Any) -> None:
    schema = pa.schema([pa.field("value", arrow_type)])
    if expected is None:
        with pytest.raises(ApplicationError):
            gigahog_columns([("a.parquet", schema)])
        return
    (column,) = gigahog_columns([("a.parquet", schema)])
    assert (column.type, column.type_params) == expected
