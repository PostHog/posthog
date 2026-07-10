#!/usr/bin/env python3
"""Build the dev knowledge graph from PostHog Code task history.

Stdlib-only. Fetches the caller's agent conversations (tasks), classifies them
into themes, extracts PR links, merges the curated learnings from
learnings.json, and renders everything into a single self-contained HTML file.
"""

# ruff: noqa: T201 — this is a CLI; it prints its result summary.

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT_DIR = HERE / "out"

# Keyword rules run in order against title + description; a task can match many.
THEME_RULES: list[tuple[str, str, str]] = [
    (
        "pr-fleet",
        "PR fleet automation",
        r"ci shepherd|pr-shepherd|review triage|stamphog|mergeable state|update.*(?:with|from) trunk|conflicting pr",
    ),
    ("pr-adoption", "Adopting existing PRs", r"\badopt\b.*\b(?:pr|pull)|take over pr"),
    ("autoresearch", "Autoresearch optimization loops", r"autoresearch"),
    (
        "ci-test-perf",
        "CI & test performance",
        r"test (?:speed|runtime|wall.?time|suite)|slow (?:test|rtl)|pytest boot|related.tests|flak[ey]|quarantin|trunk\.io|junit|ci speed|paths.filter|preflight",
    ),
    ("bundle-size", "Bundle size & eager graph", r"bundle size|eager graph|lazy.load|toolbar bundle"),
    (
        "error-noise",
        "Error tracking noise reduction",
        r"capture_?exception|error.tracking (?:noise|issue)|benign|unhandled|uncaught|swallow|suppress|noise leaking|guard (?:against|undefined)",
    ),
    ("taxonomic-filter", "Taxonomic filter", r"taxonomic|property picker|no results"),
    ("replay", "Session replay", r"replay|recording|heatmap|clickmap|toolbar"),
    ("mcp-analytics", "MCP analytics", r"mcp.analytics|harness|tool call"),
    ("dashboards-insights", "Dashboards & insights", r"dashboard|insight|tile serializ"),
    (
        "meta-analytics",
        "Measuring the dev system itself",
        r"cost per pr|engineering analytics|denial accuracy|percentage of approved|conversation frequency|detached element",
    ),
    (
        "infra-devx",
        "Infra & devex",
        r"hobby|docker.compose|devbox|hogli|sandbox|github actions|workflow|ci comment|bot comment",
    ),
]

PR_RE = re.compile(r"(?:github\.com/PostHog/posthog/pull/|(?:\bpr\b|pull request)\s*#?\s*|#)(\d{4,6})", re.IGNORECASE)


def fetch_tasks(host: str, key: str, project: int, repository: str, since: datetime) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"limit": 100, "repository": repository, "internal": "all", "archived": "all"})
    url: str | None = f"{host.rstrip('/')}/api/projects/{project}/tasks/?{params}"
    me_req = urllib.request.Request(f"{host.rstrip('/')}/api/users/@me/", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(me_req) as resp:
        my_id = json.load(resp)["id"]
    tasks: list[dict[str, Any]] = []
    since_iso = since.isoformat()
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req) as resp:
            page = json.load(resp)
        results = page["results"]
        tasks.extend(t for t in results if t["created_at"] >= since_iso)
        if not results or results[-1]["created_at"] < since_iso:
            break
        url = page.get("next")
    # The list endpoint has no created_by filter guarantee across versions, so filter locally when present.
    return [t for t in tasks if not t.get("created_by") or t["created_by"].get("id") == my_id]


def classify(task: dict[str, Any]) -> list[str]:
    text = f"{task.get('title') or ''} {task.get('description') or ''}".lower()
    themes = [key for key, _, pattern in THEME_RULES if re.search(pattern, text)]
    if task.get("origin_product") == "signal_report":
        themes.append("signals-inbox")
    return themes or ["misc"]


def extract_prs(task: dict[str, Any]) -> set[int]:
    text = f"{task.get('title') or ''} {task.get('description') or ''}"
    return {int(m) for m in PR_RE.findall(text)}


def build_graph(tasks: list[dict[str, Any]], learnings: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def add_node(node_id: str, kind: str, label: str, **extra: Any) -> None:
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "kind": kind, "label": label, **extra}

    def add_edge(source: str, target: str, kind: str) -> None:
        edges.append({"source": source, "target": target, "kind": kind})

    add_node("theme:signals-inbox", "theme", "Signals inbox reports")
    add_node("theme:misc", "theme", "Uncategorized")
    for key, label, _ in THEME_RULES:
        add_node(f"theme:{key}", "theme", label)

    task_ids_present: set[int] = set()
    for task in tasks:
        tid = f"task:{task['task_number']}"
        task_ids_present.add(task["task_number"])
        add_node(
            tid,
            "task",
            task.get("title") or f"(untitled) #{task['task_number']}",
            date=task["created_at"][:10],
            origin=task.get("origin_product", "unknown"),
            url=task.get("_posthogUrl", ""),
            detail=(task.get("description") or "")[:600],
        )
        for theme in classify(task):
            add_edge(tid, f"theme:{theme}", "in-theme")
        for pr in extract_prs(task):
            pr_id = f"pr:{pr}"
            add_node(pr_id, "pr", f"PR #{pr}", url=f"https://github.com/PostHog/posthog/pull/{pr}")
            add_edge(tid, pr_id, "worked-on")

    for learning in learnings:
        lid = f"learning:{learning['id']}"
        add_node(lid, "learning", learning["title"], detail=learning.get("body", ""))
        for theme in learning.get("themes", []):
            add_node(f"theme:{theme}", "theme", theme)
            add_edge(lid, f"theme:{theme}", "about")
        for task_number in learning.get("evidence_tasks", []):
            if task_number in task_ids_present:
                add_edge(lid, f"task:{task_number}", "evidenced-by")
        for skill in learning.get("skills", []):
            sid = f"skill:{skill['name']}"
            add_node(sid, "skill", skill["name"], status=skill.get("status", "proposed"))
            add_edge(lid, sid, "encoded-in")

    # Drop theme nodes with no edges so unused rules don't clutter the graph.
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = {k: v for k, v in nodes.items() if v["kind"] != "theme" or k in connected}
    return {"nodes": list(nodes.values()), "edges": edges, "generated_at": datetime.now(UTC).isoformat()}


def render(graph: dict[str, Any]) -> str:
    template = (HERE / "template.html").read_text()
    payload = json.dumps(graph).replace("</", "<\\/")
    return template.replace("/*__GRAPH_DATA__*/null", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--project", type=int, default=int(os.environ.get("POSTHOG_PROJECT_ID", "2")))
    parser.add_argument("--repository", default="posthog/posthog")
    parser.add_argument("--host", default=os.environ.get("POSTHOG_API_URL", "https://us.posthog.com"))
    parser.add_argument("--from-file", help="Skip the API and load a previously saved tasks.json")
    args = parser.parse_args()

    if args.from_file:
        tasks = json.loads(Path(args.from_file).read_text())
    else:
        key = os.environ.get("POSTHOG_PERSONAL_API_KEY")
        if not key:
            sys.exit("Set POSTHOG_PERSONAL_API_KEY or pass --from-file")
        since = datetime.now(UTC) - timedelta(days=args.days)
        tasks = fetch_tasks(args.host, key, args.project, args.repository, since)

    learnings = json.loads((HERE / "learnings.json").read_text())["learnings"]
    graph = build_graph(tasks, learnings)

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "tasks.json").write_text(json.dumps(tasks, indent=1))
    (OUT_DIR / "graph.html").write_text(render(graph))
    kinds: dict[str, int] = {}
    for node in graph["nodes"]:
        kinds[node["kind"]] = kinds.get(node["kind"], 0) + 1
    print(f"{len(tasks)} tasks -> {len(graph['nodes'])} nodes ({kinds}), {len(graph['edges'])} edges")
    print(f"open {OUT_DIR / 'graph.html'}")


if __name__ == "__main__":
    main()
