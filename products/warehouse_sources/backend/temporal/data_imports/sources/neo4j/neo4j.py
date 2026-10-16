import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlsplit

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.neo4j import Neo4jSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.settings import (
    API_VERSION,
    MAX_ROWS_PER_SYNC,
    NON_RETRYABLE_ERRORS,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
)


class Neo4jQueryError(Exception):
    pass


class Neo4jClient:
    def __init__(self, config: Neo4jSourceConfig, team_id: int) -> None:
        self.config = config
        self.team_id = team_id

    def query(self, statement: str, parameters: dict[str, int | str] | None = None) -> list[dict[str, Any]]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
            ValidateDatabaseHostMixin,  # noqa: PLC0415 - Keep Django models off the config import path.
        )

        host = self.config.host
        try:
            parsed = urlsplit(host)
            valid_url = (
                parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.path in ("", "/")
                and not parsed.query
                and not parsed.fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535)
                and not any(character.isspace() or character == "\\" for character in host)
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError("Invalid Neo4j host")
        assert parsed.hostname is not None
        valid_host, _ = ValidateDatabaseHostMixin().is_database_host_valid(parsed.hostname, self.team_id)
        if not valid_host:
            raise ValueError("Invalid Neo4j host")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", self.config.database):
            raise ValueError("Invalid Neo4j database")
        url = f"{host.rstrip('/')}/db/{quote(self.config.database, safe='')}/query/{API_VERSION}"
        with make_tracked_session(
            retry=DEFAULT_RETRY.new(allowed_methods=frozenset({"POST"})),
            headers={"Accept": "application/json"},
            redact_values=(self.config.password,),
            allow_redirects=False,
        ) as session:
            response = session.post(
                url,
                auth=HTTPBasicAuth(self.config.username, self.config.password),
                json={"statement": statement, "parameters": parameters or {}, "accessMode": "Read"},
                timeout=REQUEST_TIMEOUT,
            )
            if 300 <= response.status_code < 400:
                raise ValueError("Neo4j redirects are not allowed")
            response.raise_for_status()
            payload = response.json()
        if payload.get("errors"):
            codes = [str(error.get("code", "Unknown")) for error in payload["errors"]]
            raise Neo4jQueryError("Neo4j query failed: " + ", ".join(codes))
        data = payload["data"]
        return [dict(zip(data["fields"], values, strict=True)) for values in data["values"]]

    def discover_tables(self) -> list[str]:
        labels = self.query("CALL db.labels() YIELD label RETURN label ORDER BY label")
        relationships = self.query(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType"
        )
        return [f"node_{row['label']}" for row in labels] + [f"rel_{row['relationshipType']}" for row in relationships]

    @staticmethod
    def table_query(table: str) -> str:
        prefix, separator, name = table.partition("_")
        if not separator or prefix not in ("node", "rel") or not name:
            raise ValueError("Invalid Neo4j table")
        identifier = "`" + name.replace("`", "``") + "`"
        # Cypher interprets Unicode escapes in identifiers. Parameters preserve names that contain backslashes.
        if prefix == "node":
            match = "MATCH (x) WHERE $name IN labels(x)" if "\\" in name else f"MATCH (x:{identifier})"
            fields = "labels(x) AS labels"
        else:
            match = "MATCH (a)-[x]->(b) WHERE type(x) = $name" if "\\" in name else f"MATCH (a)-[x:{identifier}]->(b)"
            fields = "elementId(a) AS start_element_id, elementId(b) AS end_element_id"
        return (
            f"{match} RETURN elementId(x) AS element_id, properties(x) AS properties, {fields} "
            "ORDER BY elementId(x) SKIP $offset LIMIT $limit"
        )

    def rows(self, table: str) -> Iterator[list[dict[str, Any]]]:
        statement = self.table_query(table)
        offset = 0
        while True:
            limit = min(PAGE_SIZE, MAX_ROWS_PER_SYNC - offset + 1)
            parameters: dict[str, int | str] = {"offset": offset, "limit": limit}
            if "\\" in table:
                parameters["name"] = table.partition("_")[2]
            page = self.query(statement, parameters)
            if offset + len(page) > MAX_ROWS_PER_SYNC:
                raise ValueError("Neo4j sync row limit exceeded")
            if not page:
                return
            rows = []
            for record in page:
                properties = record.pop("properties")
                if properties.keys() & record.keys():
                    raise ValueError("Neo4j property conflicts with a reserved column name")
                rows.append({**properties, **record})
            yield rows
            offset += len(page)
            if len(page) < limit:
                return


def validate_credentials(config: Neo4jSourceConfig, team_id: int) -> tuple[bool, str | None]:
    try:
        Neo4jClient(config, team_id).query("RETURN 1 AS ok")
    except Exception as error:
        for pattern, message in NON_RETRYABLE_ERRORS.items():
            if pattern in str(error):
                return False, message
        return False, "Could not connect to Neo4j. Check the host, database, and Query API availability."
    return True, None


def neo4j_source(config: Neo4jSourceConfig, team_id: int, table: str) -> SourceResponse:
    client = Neo4jClient(config, team_id)
    client.table_query(table)
    return SourceResponse(
        name=table, items=lambda: client.rows(table), primary_keys=["element_id"], supports_resume=False
    )
