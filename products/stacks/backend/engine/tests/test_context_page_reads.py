from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import urlencode

import pytest

from products.stacks.backend.engine import (
    EngineError,
    kind_scopes,
    natural_key_kinds,
    read_entities,
    translate_in,
    validate_description,
)
from products.stacks.backend.engine.addresses import address
from products.stacks.backend.engine.claims import adoption_id
from products.stacks.backend.engine.mappings import load_mapping
from products.stacks.backend.engine.natural_keys import natural_imports
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.types import ClaimedEntity, Credentials, StackDescription

PAGES = "/api/projects/7/context_layer/agent/pages/"
ORGS = "/api/organizations/"
ORG = "aa5f50b2-a06c-4fe9-9cd6-d07ffe8b110f"
TREE = ORGS + ORG + "/context_layer/tree/"
PATH = "areas/Checkout & 100% ${quarter}.md"
HEAD = "e" * 40
CONTENT = "---\nsummary: Checkout\n---\n# Quarterly 🔎\n"


def _desc(path: str = PATH, content: str = CONTENT) -> StackDescription:
    return {
        "version": 1,
        "resources": [{"kind": "context_page", "key": path, "body": {"path": path, "content": content}}],
    }


def _url(path: str, head: str | None = None) -> str:
    return PAGES + "?" + urlencode({"path": path, **({"head_sha": head} if head else {})})


def _page(path: str, content: str = CONTENT) -> dict[str, Any]:
    return {
        "path": path,
        "content": content,
        "head_sha": HEAD,
        "updated_at": "ignored",
        "offset": 0,
        "next_offset": None,
        "complete": True,
        "total_length": len(content),
    }


@contextmanager
def _wiki(routes: dict[str, Any]) -> Iterator[tuple[Credentials, list[str]]]:
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            calls.append(self.path)
            reply = routes.get(self.path, (404, {}))
            if self.headers.get("Authorization") != "Bearer test-key":
                reply = 403, {}
            status, value = reply if isinstance(reply, tuple) else (200, reply)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

    with HTTPServer(("127.0.0.1", 0), Handler) as api:
        worker = Thread(target=api.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            yield {"host": f"http://127.0.0.1:{api.server_port}", "project_id": 7, "api_key": "test-key"}, calls
        finally:
            api.shutdown()
            worker.join()


def test_translates_context_page_as_a_shared_path_and_preserves_markdown() -> None:
    doc = _desc()
    dest = address("context_page", PATH)
    cfg = translate_in(doc, [{"kind": "context_page", "key": PATH, "entity_id": PATH, "status": "pending"}], {}).config
    resource, label = dest.split(".")
    assert cfg["resource"][resource][label] == {
        "path": PATH.replace("${", "$${"),
        "content": CONTENT,
        "lifecycle": {"prevent_destroy": True},
    }
    assert cfg["import"] == [{"to": dest, "id": "${var.stack_project_id}/" + PATH.replace("${", "$${")}]
    assert adoption_id("context_page", {"before": {"id": PATH}, "importing": {"id": "7/" + PATH}}) == PATH
    assert "context_page" in natural_key_kinds() and load_mapping("context_page")["ownership_scope"] == "organization"
    assert kind_scopes("context_page") == {
        "read": ["organization:read"],
        "write": ["organization:read", "organization:write"],
    }


@pytest.mark.parametrize(
    "path",
    [
        "/org/path.md",
        "../org/x.md",
        "areas/../org/x.md",
        "org//x.md",
        "org/./x.md",
        "areas/.git/a.md",
        "areas/index.md",
        "index.md",
        "README.md",
        "CLAUDE.md",
        "scripts/a.md",
        "org/readme.txt",
        "decisions/no-date.md",
        "org/\0bad.md",
        "org/" + "x" * 506 + ".md",
    ],
)
def test_invalid_paths_never_become_api_requests(path: str) -> None:
    error = validate_description(_desc(path), [])[0]
    assert (error.get("kind"), error.get("path")) == ("context_page", "key")
    with _wiki({}) as (credentials, requests), pytest.raises(EngineError):
        read_entities("context_page", credentials, ids=[path])
    assert not requests


def test_context_path_and_content_follow_the_write_shape() -> None:
    assert not validate_description(_desc("AGENTS.md"), [])
    assert not validate_description(_desc("decisions/2026-01-31-conventions.md"), [])
    assert not validate_description(_desc("org/" + "ü" * 505 + ".md"), [])
    desc = _desc()
    desc["resources"][0]["body"]["path"] = "org/wrong.md"
    assert validate_description(desc, [])[0]["path"] == "path"
    del desc["resources"][0]["body"]["path"]
    assert validate_description(desc, [])[0]["path"] == "path"
    for value in (None, 17, "ü" * 500001):
        desc = _desc()
        desc["resources"][0]["body"]["content"] = value
        assert validate_description(desc, [])[0]["path"] == "content"
    desc = _desc()
    del desc["resources"][0]["body"]["content"]
    assert validate_description(desc, [])[0]["path"] == "content"


def test_direct_reads_and_natural_imports_keep_the_full_path() -> None:
    with _wiki({_url(PATH): _page(PATH)}) as (credentials, requests):
        assert read_entities("context_page", credentials, ids=[PATH, PATH]) == {
            "results": [{"name": PATH, "entity_id": PATH, "body": {"path": PATH, "content": CONTENT}}],
            "next_cursor": None,
        }
        known: dict[str, str | int] = {}
        imports = natural_imports(
            translate_in(_desc(content="A reviewed edit"), [], {}), set(), credentials, found_ids=known
        )
        target = address("context_page", PATH)
        assert imports == [{"to": target, "id": "${var.stack_project_id}/" + PATH.replace("${", "$${")}]
        assert known == {target: PATH}
        assert requests == [_url(PATH), _url(PATH)]


def test_pull_preserves_markdown_whitespace_with_universal_line_endings() -> None:
    with _wiki({_url(PATH): _page(PATH, "Heading\r\n\rKeep two spaces  \rfinal")}) as (credentials, _):
        (page,) = read_entities("context_page", credentials, ids=[PATH])["results"]
    assert page["body"]["content"] == "Heading\n\nKeep two spaces  \nfinal"


def test_wiki_tree_uses_the_organization_that_contains_the_project() -> None:
    other = "org/People.md"
    organizations = {"id": ORG, "teams": [{"id": 7}]}
    routes = {
        ORGS: {"results": [{"id": "other", "teams": [{"id": 70}]}], "next": "?offset=1"},
        ORGS + "?offset=1": {"results": [organizations, organizations], "next": None},
        TREE: {"head_sha": HEAD, "paths": ["index.md", PATH, "org/index.md", other, PATH]},
        _url(PATH, HEAD): _page(PATH),
        _url(other, HEAD): _page(other),
    }
    with _wiki(routes) as (credentials, requests):
        first = read_entities("context_page", credentials, limit=1)
        assert [row["entity_id"] for row in first["results"]] == [PATH]
        assert first["next_cursor"] is not None
        second = read_entities("context_page", credentials, cursor=first["next_cursor"], limit=1)
        assert [row["entity_id"] for row in second["results"]] == [other] and second["next_cursor"] is None
        assert requests.count(_url(PATH, HEAD)) == 1


@pytest.mark.parametrize(
    "organizations",
    [[], [{"id": ORG, "teams": [{"id": 7}]}, {"id": "8937ed49-fa14-4a1f-be72-f0672490fe5d", "teams": [{"id": 7}]}]],
)
def test_listing_refuses_missing_or_ambiguous_project_membership(organizations: list) -> None:
    with _wiki({ORGS: {"results": organizations}}) as (credentials, requests), pytest.raises(EngineError):
        read_entities("context_page", credentials)
    assert requests == [ORGS]


@pytest.mark.parametrize(
    ("status", "problem", "code"),
    [
        (403, {"code": "feature_flag_required", "detail": "Not public"}, "context_layer_not_enabled"),
        (404, {"detail": "The context layer is not enabled for this organization."}, "context_layer_not_enabled"),
        (403, {"code": "permission_denied"}, "credentials_invalid"),
        (404, {"detail": "Not found."}, "entity_missing"),
        (404, {"detail": "no page at org/different.md"}, "entity_missing"),
    ],
)
def test_only_the_named_missing_page_counts_as_absent(status: int, problem: dict, code: str) -> None:
    spec = translate_in(_desc(), [], {})
    with _wiki({_url(PATH): (status, problem)}) as (credentials, _), pytest.raises(EngineError) as error:
        natural_imports(spec, set(), credentials)
    assert error.value.errors[0]["code"] == code
    assert not ENGINE_WORDS.search(str(error.value))
    with _wiki({_url(PATH): (404, {"detail": "no page at " + PATH})}) as (credentials, _):
        assert not natural_imports(spec, set(), credentials)


@pytest.mark.parametrize(
    "fields",
    [{"path": "org/wrong.md"}, {"complete": False}, {"next_offset": 10}, {"total_length": 2}, {"head_sha": ""}],
)
def test_partial_or_mismatched_pages_cannot_be_adopted(fields: dict) -> None:
    with _wiki({_url(PATH): {**_page(PATH), **fields}}) as (credentials, _), pytest.raises(EngineError):
        read_entities("context_page", credentials, ids=[PATH])


def test_paging_restarts_if_the_wiki_changed_since_the_previous_page() -> None:
    other = "org/People.md"
    routes: dict[str, Any] = {
        ORGS: [{"id": ORG, "teams": [{"id": 7}]}],
        TREE: {"head_sha": HEAD, "paths": [PATH, other]},
        _url(PATH, HEAD): _page(PATH),
        _url(other, "f" * 40): {**_page(other), "head_sha": "f" * 40},
    }
    with _wiki(routes) as (credentials, requests):
        cursor = read_entities("context_page", credentials, limit=1)["next_cursor"]
        assert cursor is not None
        routes[TREE] = {"head_sha": "f" * 40, "paths": [PATH, other]}
        with pytest.raises(EngineError) as error:
            read_entities("context_page", credentials, limit=1, cursor=cursor)
        assert error.value.errors[0]["code"] == "stack_moved"
        assert _url(other, "f" * 40) not in requests


def test_claims_distinguish_two_pages_with_the_same_filename() -> None:
    doc = _desc()
    other = "org/" + PATH.rsplit("/", 1)[1]
    claim: ClaimedEntity = {"kind": "context_page", "entity_id": other, "stack": "other", "repository": "example/repo"}
    with _wiki({_url(PATH): _page(PATH)}) as (credentials, _):
        assert natural_imports(translate_in(doc, [], {"claimed": [claim]}), set(), credentials)
        with pytest.raises(EngineError) as error:
            natural_imports(translate_in(doc, [], {"claimed": [{**claim, "entity_id": PATH}]}), set(), credentials)
        assert error.value.errors[0]["code"] == "claimed_by_other_stack"
    assert validate_description(doc, [{"kind": "context_page", "key": PATH, "entity_id": other, "status": "pending"}])
