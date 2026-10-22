from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import JsonValue, TypeAdapter

if TYPE_CHECKING:
    from httpx import BaseTransport


class SourceExportError(ValueError):
    pass


def object_value(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise SourceExportError("The source API returned an unexpected object shape.")
    return value


def array_value(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        raise SourceExportError("The source API returned an unexpected list shape.")
    return value


def timestamp(value: JsonValue) -> datetime:
    if not isinstance(value, str):
        raise SourceExportError("A source timestamp is missing.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SourceExportError("A source timestamp has no timezone.")
    return parsed


class SourceAPI:
    def __init__(
        self,
        origin: str,
        *,
        token_env: str,
        project_id: int,
        transport: BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise SourceExportError("Use an HTTPS source origin, or an explicit loopback HTTP origin.")
        token = os.environ.get(token_env)
        if not token or any(character.isspace() for character in token):
            raise SourceExportError("The named token environment variable is missing or invalid.")
        self.origin = origin.rstrip("/")
        self.project_path = f"/api/projects/{project_id}/"
        self.client = httpx.Client(
            headers={"Authorization": "Bearer " + token},
            follow_redirects=False,
            trust_env=False,
            timeout=60,
            transport=transport,
        )
        self.read_count = 0

    def close(self) -> None:
        self.client.close()

    def read(
        self,
        path: str,
        *,
        params: Mapping[str, str | int | bool] | None = None,
        query: str | None = None,
    ) -> JsonValue:
        target = urljoin(self.origin + "/", path)
        parsed = urlsplit(target)
        if parsed.scheme + "://" + parsed.netloc != self.origin or parsed.fragment:
            raise SourceExportError("The source API tried to leave its configured origin.")
        if not parsed.path.startswith(self.project_path) and parsed.path != "/api/users/@me/":
            raise SourceExportError("The source API tried to leave its selected project.")
        if query is not None and parsed.path != self.project_path + "query/":
            raise SourceExportError("Only the query endpoint accepts a read query body.")
        try:
            response = self.client.request(
                "POST" if query is not None else "GET",
                target,
                params=params,
                json={"query": {"kind": "HogQLQuery", "query": query}, "refresh": "force_blocking"}
                if query is not None
                else None,
            )
        except httpx.HTTPError:
            raise SourceExportError(
                "The source API request failed; credentials and response bodies were withheld."
            ) from None
        self.read_count += 1
        if response.status_code != 200:
            raise SourceExportError(f"The source API returned HTTP {response.status_code}; no fallback was attempted.")
        try:
            return TypeAdapter(JsonValue).validate_json(response.content)
        except ValueError:
            raise SourceExportError("The source API returned invalid JSON; the response body was withheld.") from None

    def query(self, query: str) -> list[list[JsonValue]]:
        result = object_value(self.read(self.project_path + "query/", query=query))
        if result.get("error") or not isinstance(result.get("results"), list):
            raise SourceExportError("The source query failed or did not complete synchronously.")
        rows = array_value(result.get("results"))
        return [array_value(row) for row in rows]

    def pages(self, path: str, *, max_rows: int) -> Iterator[dict[str, JsonValue]]:
        seen: set[str] = set()
        total = 0
        while path:
            if path in seen:
                raise SourceExportError("The source API returned a repeated pagination link.")
            seen.add(path)
            page = object_value(self.read(path))
            for value in array_value(page.get("results")):
                total += 1
                if total > max_rows:
                    raise SourceExportError("The selected source context exceeds the explicit export limit.")
                yield object_value(value)
            next_path = page.get("next")
            if next_path is not None and not isinstance(next_path, str):
                raise SourceExportError("The source API returned an invalid pagination link.")
            path = next_path or ""

    def dated_rows(
        self,
        path: str,
        *,
        date_field: str,
        identity_field: str,
        start: datetime | None,
        end: datetime,
        cap: int,
        max_rows: int,
        params: Mapping[str, str | int | bool] | None = None,
    ) -> list[dict[str, JsonValue]]:
        rows: dict[str, dict[str, JsonValue]] = {}
        upper = end
        while True:
            page = [
                object_value(value)
                for value in array_value(
                    self.read(
                        path,
                        params={
                            **(params or {}),
                            **({"date_from": start.isoformat()} if start else {}),
                            "date_to": upper.isoformat(),
                            "limit": cap,
                        },
                    )
                )
            ]
            if not page:
                break
            dates = [timestamp(row.get(date_field)) for row in page]
            if dates != sorted(dates, reverse=True) or any(
                date >= upper or (start is not None and date < start) for date in dates
            ):
                raise SourceExportError("The source API returned rows outside its ordered time window.")
            for row in page:
                identity = row.get(identity_field)
                if not isinstance(identity, str) or not identity:
                    raise SourceExportError("A source context row has no stable identity.")
                if identity in rows and rows[identity] != row:
                    raise SourceExportError("Source context changed while exporting; retry with a fresh output.")
                rows[identity] = row
            if len(rows) > max_rows:
                raise SourceExportError("The selected source context exceeds the explicit export limit.")
            if len(page) < cap:
                break
            boundary = dates[-1]
            if boundary == dates[0]:
                raise SourceExportError("Too many source rows share one timestamp for lossless API pagination.")
            # Overlap the final timestamp so a page boundary cannot silently discard ties.
            upper = boundary + timedelta(microseconds=1)
        return list(rows.values())
