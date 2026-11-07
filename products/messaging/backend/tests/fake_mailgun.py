"""Answers Mailgun's documented read endpoints from invented data, as a real server or as a `requests.get` stand-in.

Shapes come from Mailgun's OpenAPI spec: https://documentation.mailgun.com/_spec/docs/mailgun/api-reference/send/mailgun.json
"""

import re
import json
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "mailgun_account.json").read_text())

FULL_KEY = "full-access-key"
ANALYST_KEY = "analyst-role-key"
EMPTY_KEY = "empty-account-key"
EU_ONLY_KEY = "eu-only-key"

# Every read the importer may make. A request outside this list answers 404 and lands in `undocumented`.
DOCUMENTED_PATHS = (
    r"/v4/domains",
    r"/v4/domains/[^/]+",
    r"/v3/domains/[^/]+/tracking",
    r"/v5/accounts/subaccounts",
    r"/v3/[^/]+/(?:bounces|complaints|unsubscribes|whitelists)",
    r"/v3/lists/pages",
    r"/v3/lists/[^/]+/members/pages",
    r"/v4/templates",
    r"/v4/templates/[^/]+",
    r"/v4/templates/[^/]+/versions",
    r"/v4/templates/[^/]+/versions/[^/]+",
    r"/v3/[^/]+/templates",
    r"/v3/[^/]+/templates/[^/]+",
    r"/v3/[^/]+/templates/[^/]+/versions",
    r"/v3/[^/]+/templates/[^/]+/versions/[^/]+",
)
_DOCUMENTED = re.compile("^(?:" + "|".join(DOCUMENTED_PATHS) + ")$")


@dataclass(frozen=False)
class Failure:
    pattern: str
    status: int
    times: int = 1
    headers: dict[str, str] = field(default_factory=dict)
    # Only fail a later page, so the first page of the same list still answers.
    only_later_pages: bool = False


class FakeMailgun:
    def __init__(self, hosts: dict[str, str], data: dict[str, Any] | None = None) -> None:
        # Base URL -> region, so a request can only be answered by the region it was sent to.
        self.hosts = hosts
        self.data = data if data is not None else json.loads(json.dumps(FIXTURES))
        self.keys = {FULL_KEY, ANALYST_KEY, EMPTY_KEY, EU_ONLY_KEY}
        self.calls: list[dict[str, Any]] = []
        self.undocumented: list[str] = []
        self.failures: list[Failure] = []
        # Where `paging.next` points, to prove a wrong host in a response gets no key.
        self.paging_host: str | None = None

    def handle(
        self, base_url: str, path: str, query: dict[str, str], authorization: str, on_behalf_of: str | None
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        region = self.hosts[base_url]
        self.calls.append(
            {
                "region": region,
                "path": path,
                "query": query,
                "authorization": authorization,
                "on_behalf_of": on_behalf_of,
            }
        )
        for failure in self.failures:
            is_later_page = query.get("page") == "next"
            if (
                failure.times > 0
                and re.search(failure.pattern, path)
                and (is_later_page or not failure.only_later_pages)
            ):
                failure.times -= 1
                return failure.status, {"message": f"Forced {failure.status}"}, failure.headers
        key = _basic_key(authorization)
        if key not in self.keys:
            return 401, {"message": "Invalid private key"}, {}
        if not _DOCUMENTED.match(path):
            self.undocumented.append(path)
            return 404, {"message": "Not found"}, {}
        if key == ANALYST_KEY and re.search(r"/(bounces|complaints|unsubscribes)$", path):
            return 403, {"message": "Forbidden"}, {}
        if key == EMPTY_KEY or (key == EU_ONLY_KEY and region != "eu"):
            account: dict[str, Any] = {}
        else:
            account = self.data.get(region, {})
        return self._route(base_url, account, path, query, on_behalf_of or "")

    def _route(
        self, base_url: str, account: dict[str, Any], path: str, query: dict[str, str], owner: str
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        limit = int(query.get("limit") or 100)
        if path == "/v4/domains":
            domains = sorted(account.get("domains", []), key=lambda domain: domain["name"])
            if query.get("include_subaccounts") != "true":
                domains = [domain for domain in domains if not domain.get("subaccount_id")]
            skip = int(query.get("skip") or 0)
            return 200, {"total_count": len(domains), "items": domains[skip : skip + limit]}, {}
        if path == "/v5/accounts/subaccounts":
            rows = account.get("subaccounts", [])
            skip = int(query.get("skip") or 0)
            return 200, {"subaccounts": rows[skip : skip + limit], "total": len(rows)}, {}
        if match := re.fullmatch(r"/v4/domains/([^/]+)", path):
            name = unquote(match.group(1))
            domain = next((row for row in account.get("domains", []) if row["name"] == name), None)
            if domain is None:
                return 404, {"message": "Domain not found"}, {}
            return 200, {"domain": domain, **account.get("domain_details", {}).get(name, {})}, {}
        if match := re.fullmatch(r"/v3/domains/([^/]+)/tracking", path):
            name = unquote(match.group(1))
            return 200, {"tracking": account.get("tracking", {}).get(name, {"unsubscribe": {"active": False}})}, {}
        if path == "/v3/lists/pages":
            return self._by_pivot(base_url, path, account.get("lists", {}).get(owner, []), query, "address", limit)
        if match := re.fullmatch(r"/v3/lists/([^/]+)/members/pages", path):
            members = account.get("members", {}).get(unquote(match.group(1)))
            if members is None and not any(
                row["address"] == unquote(match.group(1)) for rows in account.get("lists", {}).values() for row in rows
            ):
                return 404, {"message": "Mailing list not found"}, {}
            members = members or []
            if "subscribed" in query:
                wanted = query["subscribed"].lower() in ("true", "yes")
                members = [member for member in members if member["subscribed"] is wanted]
            return self._by_pivot(base_url, path, members, query, "address", limit)
        if match := re.fullmatch(r"/v4/templates(?:/([^/]+)(/versions(?:/([^/]+))?)?)?", path):
            return self._templates(
                base_url, path, account.get("account_templates", {}).get(owner, []), match, query, limit
            )
        if match := re.fullmatch(r"/v3/([^/]+)/templates(?:/([^/]+)(/versions(?:/([^/]+))?)?)?", path):
            domain_name = unquote(match.group(1))
            if not any(row["name"] == domain_name for row in account.get("domains", [])):
                return 404, {"message": "Domain not found"}, {}
            nested = re.fullmatch(r"/v3/[^/]+/templates(?:/([^/]+)(/versions(?:/([^/]+))?)?)?", path)
            return self._templates(
                base_url, path, account.get("domain_templates", {}).get(domain_name, []), nested, query, limit
            )
        if match := re.fullmatch(r"/v3/([^/]+)/(bounces|complaints|unsubscribes|whitelists)", path):
            domain_name = unquote(match.group(1))
            if not any(row["name"] == domain_name for row in account.get("domains", [])):
                return 404, {"message": "Domain not found"}, {}
            rows = account.get(match.group(2), {}).get(domain_name, [])
            pivot = "value" if match.group(2) == "whitelists" else "address"
            return self._by_pivot(base_url, path, rows, query, pivot, limit)
        return 404, {"message": "Not found"}, {}

    def _by_pivot(
        self, base_url: str, path: str, rows: list[dict[str, Any]], query: dict[str, str], pivot: str, limit: int
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        ordered = sorted(rows, key=lambda row: row[pivot])
        if query.get("page") == "next" and "address" in query:
            ordered = [row for row in ordered if row[pivot] > query["address"]]
        page = ordered[:limit]
        # Mailgun's last page still names a next page, which comes back empty.
        last = page[-1][pivot] if page else query.get("address", "")
        return (
            200,
            {
                "items": page,
                "paging": self._paging(
                    base_url, path, {"page": "next", "address": last, "limit": limit, **_kept(query)}
                ),
            },
            {},
        )

    def _templates(
        self,
        base_url: str,
        path: str,
        rows: list[dict[str, Any]],
        match: re.Match[str] | None,
        query: dict[str, str],
        limit: int,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        assert match is not None
        name, versions_part, tag = match.group(1), match.group(2), match.group(3)
        if name is None:
            ordered = sorted(rows, key=lambda row: row["name"])
            if query.get("page") == "next" and "p" in query:
                ordered = [row for row in ordered if row["name"] > query["p"]]
            page = ordered[:limit]
            last = page[-1]["name"] if page else query.get("p", "")
            listed_templates = [{key: value for key, value in row.items() if key != "versions"} for row in page]
            return (
                200,
                {
                    "items": listed_templates or None,
                    "paging": self._paging(base_url, path, {"page": "next", "p": last, "limit": limit}),
                },
                {},
            )
        template = next((row for row in rows if row["name"] == unquote(name)), None)
        if template is None:
            return 404, {"message": "template not found"}, {}
        summary = {key: value for key, value in template.items() if key != "versions"}
        versions = template.get("versions", [])
        if tag is not None:
            version = next((row for row in versions if row["tag"] == unquote(tag)), None)
            if version is None:
                return 404, {"message": "version not found"}, {}
            return 200, {"template": {**summary, "version": version}}, {}
        if versions_part:
            # The list leaves the content out, the way Mailgun's example does, so reading it needs another request.
            listed = [] if query.get("page") == "next" else [{**row, "template": ""} for row in versions]
            paging = self._paging(base_url, path, {"page": "next", "p": "end", "limit": limit})
            return 200, {"template": {**summary, "versions": listed}, "paging": paging}, {}
        if query.get("active") == "yes":
            active = next((row for row in versions if row.get("active")), None)
            return 200, {"template": {**summary, **({"version": active} if active else {})}}, {}
        return 200, {"template": summary}, {}

    def _paging(self, base_url: str, path: str, query: dict[str, Any]) -> dict[str, str]:
        base = self.paging_host or base_url
        quoted_query = urlencode(query)
        return {
            "first": f"{base}{path}?limit={query['limit']}",
            "last": f"{base}{path}?page=last&limit={query['limit']}",
            "next": f"{base}{path}?{quoted_query}",
            "previous": f"{base}{path}?page=previous&limit={query['limit']}",
        }


def _kept(query: dict[str, str]) -> dict[str, str]:
    return {"subscribed": query["subscribed"]} if "subscribed" in query else {}


def _basic_key(authorization: str) -> str:
    if not authorization.startswith("Basic "):
        return ""
    user, _, key = base64.b64decode(authorization[6:]).decode().partition(":")
    return key if user == "api" else ""


def split_url(url: str) -> tuple[str, str, dict[str, str]]:
    parts = urlsplit(url)
    return (
        f"{parts.scheme}://{parts.netloc}",
        parts.path,
        {key: values[-1] for key, values in parse_qs(parts.query).items()},
    )
