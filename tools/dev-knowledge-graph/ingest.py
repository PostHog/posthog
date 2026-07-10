#!/usr/bin/env python3
"""Build the dev knowledge graph.

The graph is knowledge-first: learning nodes carry inspectable markdown (with
PRs and conversations as links, not nodes) and connect to the parts of the
system they are about — software modules, products, user/event properties, and
the skills that encode them. Optionally overlays the conversations (PostHog
Code tasks) cited as evidence. Stdlib-only; renders a single self-contained
HTML file.
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


def fetch_tasks(
    host: str, key: str, project: int, repository: str, since: datetime, all_users: bool
) -> list[dict[str, Any]]:
    if not host.startswith(("https://", "http://")):
        sys.exit(f"--host must be an http(s) URL, got {host!r}")
    params = urllib.parse.urlencode({"limit": 100, "repository": repository, "internal": "all", "archived": "all"})
    url: str | None = f"{host.rstrip('/')}/api/projects/{project}/tasks/?{params}"
    me_req = urllib.request.Request(f"{host.rstrip('/')}/api/users/@me/", headers={"Authorization": f"Bearer {key}"})
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected — developer-run CLI; host is the operator's own API base, scheme-validated above
    with urllib.request.urlopen(me_req) as resp:
        my_id = json.load(resp)["id"]
    tasks: list[dict[str, Any]] = []
    since_iso = since.isoformat()
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected — pagination URL returned by the same scheme-validated API host
        with urllib.request.urlopen(req) as resp:
            page = json.load(resp)
        results = page["results"]
        tasks.extend(t for t in results if t["created_at"] >= since_iso)
        if not results or results[-1]["created_at"] < since_iso:
            break
        url = page.get("next")
    if all_users:
        return tasks
    # The list endpoint has no created_by filter guarantee across versions, so filter locally when present.
    return [t for t in tasks if not t.get("created_by") or t["created_by"].get("id") == my_id]


def task_author(task: dict[str, Any]) -> str:
    creator = task.get("created_by") or {}
    return (creator.get("email") or "").split("@")[0] or creator.get("first_name", "").lower() or "unknown"


def module_product(module: str) -> str | None:
    """A module under products/<name>/ belongs to that product."""
    match = re.match(r"products/([^/]+)/", module)
    return match.group(1).replace("_", " ") if match else None


def build_graph(learnings: list[dict[str, Any]], tasks: list[dict[str, Any]] | None) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def add_node(node_id: str, kind: str, label: str, **extra: Any) -> None:
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "kind": kind, "label": label, **extra}

    def add_edge(source: str, target: str, kind: str) -> None:
        edges.append({"source": source, "target": target, "kind": kind})

    tasks_by_number = {t["task_number"]: t for t in tasks or []}

    for learning in learnings:
        lid = f"learning:{learning['id']}"
        add_node(
            lid,
            "learning",
            learning["title"],
            markdown=learning.get("markdown", ""),
            author=learning.get("author", "unknown"),
            evidence_count=len(learning.get("evidence_tasks", [])),
        )
        for module in learning.get("modules", []):
            mid = f"module:{module}"
            add_node(mid, "module", module)
            add_edge(lid, mid, "about")
            if product := module_product(module):
                add_node(f"product:{product}", "product", product)
                add_edge(mid, f"product:{product}", "part-of")
        for product in learning.get("products", []):
            add_node(f"product:{product}", "product", product)
            add_edge(lid, f"product:{product}", "about")
        for prop in learning.get("properties", []):
            add_node(f"property:{prop}", "property", prop)
            add_edge(lid, f"property:{prop}", "about")
        for skill in learning.get("skills", []):
            sid = f"skill:{skill['name']}"
            add_node(sid, "skill", skill["name"], status=skill.get("status", "proposed"))
            add_edge(lid, sid, "encoded-in")
        if tasks:
            for task_number in learning.get("evidence_tasks", []):
                task = tasks_by_number.get(task_number)
                if not task:
                    continue
                tid = f"task:{task_number}"
                add_node(
                    tid,
                    "task",
                    task.get("title") or f"(untitled) #{task_number}",
                    date=task["created_at"][:10],
                    author=task_author(task),
                    url=task.get("_posthogUrl", ""),
                )
                add_edge(lid, tid, "evidenced-by")

    return {"nodes": list(nodes.values()), "edges": edges, "generated_at": datetime.now(UTC).isoformat()}


def render(graph: dict[str, Any]) -> str:
    template = (HERE / "template.html").read_text()
    payload = json.dumps(graph).replace("</", "<\\/")
    return template.replace("/*__GRAPH_DATA__*/null", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-conversations",
        action="store_true",
        help="Overlay the conversations cited as evidence (fetched from the API, or --from-file)",
    )
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--project", type=int, default=int(os.environ.get("POSTHOG_PROJECT_ID", "2")))
    parser.add_argument("--repository", default="posthog/posthog")
    parser.add_argument("--host", default=os.environ.get("POSTHOG_API_URL", "https://us.posthog.com"))
    parser.add_argument("--from-file", help="Load a previously saved tasks.json instead of calling the API")
    parser.add_argument("--all-users", action="store_true", help="Include everyone's tasks, not just your own")
    args = parser.parse_args()

    tasks: list[dict[str, Any]] | None = None
    if args.include_conversations:
        if args.from_file:
            tasks = json.loads(Path(args.from_file).read_text())
        else:
            key = os.environ.get("POSTHOG_PERSONAL_API_KEY")
            if not key:
                sys.exit("Set POSTHOG_PERSONAL_API_KEY or pass --from-file")
            since = datetime.now(UTC) - timedelta(days=args.days)
            tasks = fetch_tasks(args.host, key, args.project, args.repository, since, args.all_users)

    learnings = json.loads((HERE / "learnings.json").read_text())["learnings"]
    graph = build_graph(learnings, tasks)

    OUT_DIR.mkdir(exist_ok=True)
    if tasks is not None:
        (OUT_DIR / "tasks.json").write_text(json.dumps(tasks, indent=1))
    (OUT_DIR / "graph.html").write_text(render(graph))
    kinds: dict[str, int] = {}
    for node in graph["nodes"]:
        kinds[node["kind"]] = kinds.get(node["kind"], 0) + 1
    print(f"{len(learnings)} learnings -> {len(graph['nodes'])} nodes ({kinds}), {len(graph['edges'])} edges")
    print(f"open {OUT_DIR / 'graph.html'}")


if __name__ == "__main__":
    main()
