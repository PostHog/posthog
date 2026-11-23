from __future__ import annotations

import os
import json
import shutil
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest

from products.stacks.backend.engine import (
    Binding,
    BindingRecord,
    Credentials,
    EngineInput,
    read_bindings,
    run_diff,
    run_push,
    translate_in,
)
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS

PAGE_ROUTE = "/api/projects/7/context_layer/agent/pages/"

pytestmark = pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="The wiki round trip needs the local binary and mirror.",
)


class Wiki:
    def __init__(self) -> None:
        self.pages = {"AGENTS.md": "# Home\n"}
        self.revision = 1
        self.access_error: str | None = None
        self.error_after_commit = False
        self.calls: list[str] = []
        self.writes: list[tuple[str, str]] = []

    @property
    def head(self) -> str:
        return f"{self.revision:040x}"

    def commit(self, path: str, content: str) -> None:
        self.pages[path] = content
        self.revision += 1


@pytest.fixture
def wiki_api() -> Iterator[tuple[Wiki, Credentials]]:
    wiki = Wiki()

    class API(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            wiki.calls.append(self.command)

        def reply(self, status: int, body: object) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def can_access(self) -> bool:
            if self.headers.get("Authorization") != "Bearer example-wiki-key":
                self.reply(401, {"detail": "An API key is required."})
            elif urlsplit(self.path).path != PAGE_ROUTE:
                self.reply(404, {"detail": "Not found."})
            elif wiki.access_error == "feature_flag_required":
                self.reply(
                    403,
                    {
                        "code": wiki.access_error,
                        "detail": "This action requires feature flag 'context-layer' to be enabled for your organization.",
                    },
                )
            elif wiki.access_error:
                self.reply(
                    403, {"code": wiki.access_error, "detail": "You do not have permission to perform this action."}
                )
            else:
                return True
            return False

        def do_GET(self) -> None:
            if not self.can_access():
                return
            query = parse_qs(urlsplit(self.path).query)
            path = query.get("path", [""])[0]
            if path not in wiki.pages:
                self.reply(404, {"detail": f"no page at {path}"})
                return
            content = wiki.pages[path].replace("\r\n", "\n").replace("\r", "\n")
            offset = int(query.get("offset", ["0"])[0])
            end = min(len(content), offset + int(query.get("limit", [str(len(content))])[0]))
            self.reply(
                200,
                {
                    "path": path,
                    "head_sha": wiki.head,
                    "content": content[offset:end],
                    "offset": offset,
                    "next_offset": end if end < len(content) else None,
                    "total_length": len(content),
                    "complete": end == len(content),
                },
            )

        def do_PUT(self) -> None:
            if not self.can_access():
                return
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if value.get("base_head") != wiki.head:
                self.reply(
                    409,
                    {
                        "detail": "The wiki changed since this edit was based; re-read and retry.",
                        "current_head": wiki.head,
                    },
                )
                return
            wiki.writes.append((value["path"], wiki.head))
            wiki.commit(value["path"], value["content"])
            if wiki.error_after_commit:
                self.reply(500, {"detail": "Wiki temporarily unavailable."})
                return
            self.reply(200, {"head_sha": wiki.head})

    with HTTPServer(("127.0.0.1", 0), API) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            yield (
                wiki,
                {"host": f"http://127.0.0.1:{server.server_port}", "project_id": 7, "api_key": "example-wiki-key"},
            )
        finally:
            server.shutdown()
            worker.join()


def _pages(pages: dict[str, str], bindings: list[BindingRecord] | None = None) -> EngineInput:
    return translate_in(
        {
            "version": 1,
            "resources": [
                {"kind": "context_page", "key": path, "body": {"path": path, "content": content}}
                for path, content in pages.items()
            ],
        },
        [Binding(**b) for b in bindings or []],
        {"mirror": os.environ["POSTHOG_STACK_MIRROR"]},
    )


def test_evaluated_sdk_pages_publish_their_markdown(tmp_path: Path, wiki_api: tuple[Wiki, Credentials]) -> None:
    wiki, credentials = wiki_api
    fixture = Path(__file__).resolve().parents[5] / "packages/sdk/tests/fixtures/stack-all-kinds/description.json"
    rows = [row for row in json.loads(fixture.read_bytes())["resources"] if row["kind"] == "context_page"]
    assert len(rows) == 2
    stack = translate_in({"version": 1, "resources": rows}, [], {"mirror": os.environ["POSTHOG_STACK_MIRROR"]})
    diff, saved, _ = run_diff(tmp_path, stack, None, credentials)
    assert not diff["errors"] and diff["summary"]["create"] == len(rows)
    pushed, record = run_push(tmp_path, stack, saved, None, credentials)
    assert not pushed["errors"] and read_bindings(record) == [
        {"kind": "context_page", "key": path, "entity_id": path} for path in sorted(row["key"] for row in rows)
    ]
    assert {path for path, _ in wiki.writes} == {row["key"] for row in rows}
    for row in rows:
        assert wiki.pages[row["key"]] == row["body"]["content"]
    after, _, _ = run_diff(tmp_path, stack, record, credentials)
    assert not after["errors"] and not after["changes"] and not after["drift"]


def test_one_push_reviews_three_page_edits_and_a_create_then_releases_the_pages(
    tmp_path: Path, wiki_api: tuple[Wiki, Credentials]
) -> None:
    wiki, credentials = wiki_api
    first, second, third, fourth = (f"areas/{key}.md" for key in ("first", "second", "third", "fourth"))
    published = {first: "First page\r\n", second: "Second page\r", third: "Published introduction\n"}
    wiki.pages.update(published)
    baseline = _pages({first: "First page\n", second: "Second page\n"})
    reviewed, saved, _ = run_diff(tmp_path, baseline, None, credentials)
    assert reviewed["errors"] == []
    assert [(c["action"], c.get("entity_id"), c["fields"]) for c in reviewed["changes"]] == [
        ("adopt", first, []),
        ("adopt", second, []),
    ]
    adopted, prior = run_push(tmp_path, baseline, saved, None, credentials)
    assert adopted["errors"] == []
    assert set(wiki.calls) == {"GET"}

    desired = {
        path: f"# {name}\n"
        for path, name in [(first, "Overview"), (second, "Metrics"), (third, "Introduction"), (fourth, "FAQ")]
    }
    proposal = _pages(desired, adopted["bindings"])
    reviewed, saved, _ = run_diff(tmp_path, proposal, prior, credentials)
    assert reviewed["errors"] == []
    assert {c["key"]: c["action"] for c in reviewed["changes"]} == {
        first: "update",
        second: "update",
        third: "adopt",
        fourth: "create",
    }
    adoption = next(c for c in reviewed["changes"] if c["action"] == "adopt")
    assert adoption.get("entity_id") == third
    assert adoption["fields"] == [
        {"path": "content", "before": published[third], "after": desired[third], "sensitive": False}
    ]
    assert set(wiki.calls) == {"GET"}
    revision = wiki.revision
    pushed, record = run_push(tmp_path, proposal, saved, prior, credentials)
    assert pushed["errors"] == []
    assert {p: wiki.pages[p] for p in desired} == desired
    assert {p for p, _ in wiki.writes} == desired.keys()
    assert [base for _, base in wiki.writes] == [f"{revision + n:040x}" for n in range(4)]

    followup, _, _ = run_diff(tmp_path, _pages(desired, pushed["bindings"]), record, credentials)
    assert not followup["errors"] and not followup["changes"] and not followup["drift"]
    release = _pages({}, pushed["bindings"])
    reviewed, saved, _ = run_diff(tmp_path, release, record, credentials)
    assert reviewed["errors"] == [] and reviewed["summary"]["release"] == 4
    released, last = run_push(tmp_path, release, saved, record, credentials)
    assert released["errors"] == [] and read_bindings(last) == []
    assert len(wiki.writes) == 4 and {p: wiki.pages[p] for p in desired} == desired


def test_reserved_wiki_path_cannot_be_created_by_another_project(
    tmp_path: Path, wiki_api: tuple[Wiki, Credentials]
) -> None:
    wiki, credentials = wiki_api
    path = "org/charter.md"
    page = _pages({path: "Charter"})
    reviewed, saved, _ = run_diff(tmp_path, page, None, credentials)
    assert reviewed["errors"] == [] and reviewed["summary"]["create"] == 1
    claimed = replace(
        page,
        options={
            **page.options,
            "claimed": [{"kind": "context_page", "entity_id": path, "stack": "docs", "repository": "example/handbook"}],
        },
    )
    rejected, blocked, _ = run_diff(tmp_path, claimed, None, credentials)
    assert [error["code"] for error in rejected["errors"]] == ["claimed_by_other_stack"] and not blocked
    pushed, _ = run_push(tmp_path, claimed, saved, None, credentials)
    assert [error["code"] for error in pushed["errors"]] == ["claimed_by_other_stack"]
    assert not wiki.writes


@pytest.mark.parametrize(
    ("committed_before_error", "expected_code"),
    [(False, "stack_moved"), (True, "context_page_write_uncertain")],
)
def test_wiki_conflict_reports_whether_the_reviewed_edit_may_have_been_saved(
    tmp_path: Path, wiki_api: tuple[Wiki, Credentials], committed_before_error: bool, expected_code: str
) -> None:
    wiki, credentials = wiki_api
    path = "areas/checkout.md"
    wiki.commit(path, "Published")
    reviewed_page = _pages({path: "Reviewed"})
    reviewed, saved, _ = run_diff(tmp_path, reviewed_page, None, credentials)
    assert reviewed["errors"] == [] and reviewed["summary"]["adopt"] == 1
    assert reviewed["changes"][0]["fields"][0]["before"] == "Published"
    if committed_before_error:
        wiki.error_after_commit = True
    else:
        wiki.commit(path, "Edited after review")
    pushed, _ = run_push(tmp_path, reviewed_page, saved, None, credentials)
    assert [e["code"] for e in pushed["errors"]] == [expected_code]
    assert not ENGINE_WORDS.search(pushed["errors"][0]["message"])
    if committed_before_error:
        assert wiki.pages[path] == "Reviewed" and len(wiki.writes) == 1
    else:
        assert wiki.pages[path] == "Edited after review" and not wiki.writes


@pytest.mark.parametrize("external_content", ["Reviewed", "Another writer"])
def test_page_created_after_review_requires_reviewing_its_adoption(
    tmp_path: Path, wiki_api: tuple[Wiki, Credentials], external_content: str
) -> None:
    wiki, credentials = wiki_api
    path = "areas/new.md"
    page = _pages({path: "Reviewed"})
    reviewed, saved, _ = run_diff(tmp_path, page, None, credentials)
    assert reviewed["errors"] == [] and reviewed["summary"]["create"] == 1
    wiki.commit(path, external_content)
    pushed, _ = run_push(tmp_path, page, saved, None, credentials)
    assert [e["code"] for e in pushed["errors"]] == ["stack_moved"]
    assert wiki.pages[path] == external_content and not wiki.writes


@pytest.mark.parametrize(
    ("denial", "code"),
    [("feature_flag_required", "context_layer_not_enabled"), ("permission_denied", "credentials_invalid")],
)
def test_context_layer_enablement_and_permission_errors(
    tmp_path: Path, wiki_api: tuple[Wiki, Credentials], denial: str, code: str
) -> None:
    wiki, credentials = wiki_api
    path = "areas/overview.md"
    wiki.commit(path, "Overview")
    page = _pages({path: "Overview"})
    reviewed, saved, _ = run_diff(tmp_path, page, None, credentials)
    assert reviewed["errors"] == [] and reviewed["summary"]["adopt"] == 1
    adopted, prior = run_push(tmp_path, page, saved, None, credentials)
    assert adopted["errors"] == []
    wiki.access_error = denial
    bound = _pages({path: "Overview"}, adopted["bindings"])
    for definition, record in ((page, None), (bound, prior)):
        diff, saved, _ = run_diff(tmp_path, definition, record, credentials)
        assert [e["code"] for e in diff["errors"]] == [code]
        assert not ENGINE_WORDS.search(diff["errors"][0]["message"])
        if denial == "feature_flag_required":
            assert "not enabled" in diff["errors"][0]["message"].lower()
        assert not saved
    assert not wiki.writes
