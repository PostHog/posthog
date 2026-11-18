import re
import json
import uuid
import datetime as dt
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
from products.managed_warehouse.backend.temporal.gigahog_client import GigahogClient, GigahogConfig
from products.managed_warehouse.backend.temporal.gigahog_register_data_imports import (
    gigahog_columns,
    gigahog_commit_refused,
    gigahog_landing_uri,
    gigahog_team_filesystem,
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

    The token endpoint answers a per-team exchange with a token and an S3 session for that team. Like the public
    listener, Gigahog refuses requests without a current token, answers 404 for another team's namespace, refuses an
    `author` from a scoped token, keeps a receipt per idempotency key, and refuses a changed body under a key it has
    seen. Namespaces exist only when the test creates them, as hogtower's provisioner does.
    """

    def __init__(self) -> None:
        self.namespaces: dict[str, dict[str, Any] | None] = {}
        self.tables: dict[tuple[str, str], dict[str, Any]] = {}
        self.live_files: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.snapshot = 1
        self.receipts: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self.commits = 0
        self.tokens_issued = 0
        self.valid_tokens: dict[str, int] = {}
        self.known_teams = {TEAM}
        self.token_expires_in = 900
        self.storage_expiration = "2099-01-01T00:00:00Z"
        # Faults the next commit request meets. "lost" commits and drops the response. "conflict" is another
        # writer's commit landing first. "unavailable" refuses without committing. "token_expired" expires the token.
        # "unauthorized" answers 401 whatever the token.
        self.commit_faults: list[str] = []
        self.token_faults: list[str] = []
        # A table another writer creates right after this writer's lookup misses it.
        self.created_concurrently: dict[str, Any] | None = None

    def install(self, mocker: requests_mock.Mocker) -> None:
        mocker.post(TOKEN_URL, json=self._token)
        mocker.register_uri(
            requests_mock.ANY, re.compile(re.escape(f"{GIGAHOG_URL}/v1/catalogs/{CATALOG}") + "(/|$)"), json=self
        )

    def mark(self, team_id: int, org: str) -> None:
        self.namespaces[f"team_{team_id}"] = {"field": "team_id", "value": team_id, "org": org}

    def _token(self, request: Any, context: Any) -> Any:
        form = parse_qs(request.body)
        team_id = int(form.pop("team_id")[0])
        assert form == {
            "grant_type": ["client_credentials"],
            "client_id": ["hlw_writer"],
            "client_secret": ["writer-secret"],
        }
        if self.token_faults:
            assert self.token_faults.pop(0) == "unavailable"
            context.status_code = 503
            return {"error": "unavailable"}
        if team_id not in self.known_teams:
            context.status_code = 400
            return {"error": "invalid_target"}
        self.tokens_issued += 1
        token = f"token-{self.tokens_issued}"
        self.valid_tokens[token] = team_id
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": self.token_expires_in,
            "storage": {
                "access_key_id": f"team-{team_id}-key",
                "secret_access_key": f"team-{team_id}-secret",
                "session_token": f"team-{team_id}-session",
                "expiration": self.storage_expiration,
                "region": "us-east-1",
                "bucket": "gigahog-bucket",
                "prefixes": [f"imports/org_id={ORG.lower()}/team_id={team_id}/"],
            },
        }

    def __call__(self, request: Any, context: Any) -> Any:
        path = request.path.removeprefix(f"/v1/catalogs/{CATALOG}")
        body: dict[str, Any] = json.loads(request.body) if request.body else {}
        if path == "/commit/replacements/prepared" and self.commit_faults[:1] == ["token_expired"]:
            self.commit_faults.pop(0)
            self.valid_tokens.clear()
        if path == "/commit/replacements/prepared" and self.commit_faults[:1] == ["unauthorized"]:
            self.commit_faults.pop(0)
            context.status_code = 401
            return {"error": "unauthorized"}
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self.valid_tokens:
            context.status_code = 401
            return {"error": "unauthorized"}
        if "author" in body:
            context.status_code = 422
            return {"error": "validation", "detail": "a scoped token cannot claim an author"}
        namespace = re.match(r"/namespaces/([^/]+)", path)
        if namespace and (
            namespace.group(1) != f"team_{self.valid_tokens[token]}" or namespace.group(1) not in self.namespaces
        ):
            context.status_code = 404
            return {"error": "namespace_not_found"}
        if match := re.fullmatch(r"/namespaces/([^/]+)", path):
            assert request.method == "GET"
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
                if self.created_concurrently is not None:
                    self.tables[(match.group(1), match.group(2))] = self.created_concurrently
                    self.live_files[(match.group(1), match.group(2))] = []
                    self.created_concurrently = None
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
    with (
        requests_mock.Mocker() as mocker,
        patch.object(client_module, "_TRANSIENT_BACKOFF_SECONDS", 0),
        patch.dict(client_module._team_credentials, clear=True),
    ):
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
    assert gigahog.tokens_issued == 1


@pytest.mark.parametrize(
    "case, exchanges",
    [
        ("cached", 1),
        ("fresh_for_a_copy", 2),
        ("other_team", 2),
        # Renewal follows the earlier of the token's and the session's expiry.
        ("token_expires_soon", 2),
        ("session_expires_soon", 2),
    ],
)
def test_team_credentials_cover_one_team_and_renew_before_they_expire(gigahog, case: str, exchanges: int) -> None:
    gigahog.known_teams.add(TEAM + 1)
    if case == "token_expires_soon":
        gigahog.token_expires_in = 120
    elif case == "session_expires_soon":
        gigahog.storage_expiration = (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    GigahogClient(CONFIG, team_id=TEAM).storage_session()
    second_team = TEAM + 1 if case == "other_team" else TEAM
    filesystem = gigahog_team_filesystem(GigahogClient(CONFIG, team_id=second_team), fresh=case == "fresh_for_a_copy")

    assert gigahog.tokens_issued == exchanges
    assert (filesystem.key, filesystem.secret, filesystem.token) == (
        f"team-{second_team}-key",
        f"team-{second_team}-secret",
        f"team-{second_team}-session",
    )
    assert filesystem.client_kwargs == {"region_name": "us-east-1"}


@pytest.mark.parametrize(
    "commit_faults, token_faults",
    [
        (["lost"], []),
        (["conflict"], []),
        (["unavailable"], []),
        (["token_expired"], []),
        # The token expires while the commit is being repeated, after the first attempt.
        (["unavailable", "token_expired"], []),
        ([], ["unavailable"]),
    ],
)
def test_a_repeated_commit_lands_the_generation_once(
    gigahog, files, commit_faults: list[str], token_faults: list[str]
) -> None:
    gigahog.commit_faults = commit_faults
    gigahog.token_faults = token_faults
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
        ("changed_columns_from_a_concurrent_create", False),
        ("unsupported_type", False),
        ("case_only_names", False),
        ("columns_with_field_ids", False),
        ("namespace_missing", True),
        ("namespace_without_org_mark", True),
        ("namespace_of_another_org", False),
        # hogtower's team sync has not reached the team yet.
        ("team_unknown_to_hogtower", True),
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
    elif case == "namespace_missing":
        del gigahog.namespaces["team_42"]
    elif case == "namespace_without_org_mark":
        gigahog.namespaces["team_42"] = None
    elif case == "team_unknown_to_hogtower":
        gigahog.known_teams.clear()
    elif case == "namespace_of_another_org":
        gigahog.mark(TEAM, str(uuid.UUID(int=1)))
    elif case.startswith("changed_columns"):
        other_table = {
            "namespace": "team_42",
            "name": TABLE,
            "table_uuid": str(uuid.uuid4()),
            "columns": [{"name": "id", "type": "string", "nullable": True}],
        }
        if case == "changed_columns":
            gigahog.tables[("team_42", TABLE)] = other_table
            gigahog.live_files[("team_42", TABLE)] = [{"path": "old"}]
        else:
            gigahog.created_concurrently = other_table
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
    if case.startswith(("namespace_", "team_")):
        assert gigahog.tables == {}
        assert ("team_42" in gigahog.namespaces) is (case != "namespace_missing")
    if case == "changed_columns":
        assert gigahog.live_files[("team_42", TABLE)] == [{"path": "old"}]


@pytest.mark.parametrize(
    "commit_faults, refused",
    [
        (["conflict"] * 3, True),
        # The first send may have committed, and a 401 on the repeat comes before Gigahog looks up its receipt.
        (["unavailable", "unauthorized", "unauthorized"], False),
    ],
)
def test_a_commit_counts_as_refused_only_when_no_send_may_have_landed(
    gigahog, files, commit_faults: list[str], refused: bool
) -> None:
    gigahog.commit_faults = commit_faults
    landing_uri = _landing_uri()
    paths = _write_generation(files, landing_uri, {"a.parquet": _charges(1)})

    with pytest.raises(ApplicationError) as raised:
        _register(files, landing_uri, paths)

    assert gigahog_commit_refused(raised.value) is refused


@pytest.mark.parametrize("newer_generation", ["before_the_sync", "after_a_conflict", "during_the_table_read"])
def test_a_stale_generation_commits_nothing(gigahog, files, newer_generation: str) -> None:
    # A newer generation's rows are in the table, so committing this one would replace them with older rows.
    if newer_generation == "after_a_conflict":
        gigahog.commit_faults = ["conflict"]
        checks = iter([True, False])
        should_publish = lambda: next(checks)
    elif newer_generation == "during_the_table_read":
        # The newer generation lands while this one reads the table, so only a check after the read sees it.
        should_publish = lambda: not gigahog.tables
    else:
        should_publish = lambda: False
    landing_uri = _landing_uri()
    paths = _write_generation(files, landing_uri, {"a.parquet": _charges(1)})

    assert _register(files, landing_uri, paths, should_publish=should_publish).published is False
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
