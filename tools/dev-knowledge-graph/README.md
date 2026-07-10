# Dev knowledge graph

A small graph database + HTML frontend of what we learn while working in this repo: "the system that builds the systems we work on".

The graph is **knowledge-first**: learning nodes carry markdown you can inspect (with PRs and conversations as links, not nodes) and connect to the parts of the system the knowledge is about — software modules, products, user/event properties, and the skills that encode them.

## Node types

| Kind | Meaning |
| --- | --- |
| `learning` | Something we learned that should outlive the conversation it came from; carries inspectable markdown |
| `module` | A software module the learning is about (e.g. `frontend/src/lib/components/TaxonomicFilter`) |
| `product` | A product or system area (e.g. `session replay`, `CI`, `PostHog Code`) |
| `property` | A user/event property the learning concerns (e.g. `$current_url`) |
| `skill` | A skill that encodes (`existing`) or should encode (`proposed`) the learning |
| `task` | A conversation cited as evidence — only with `--include-conversations` |

Edges: `learning→module/product/property` (about), `module→product` (part-of, inferred from `products/<name>/` paths), `learning→skill` (encoded-in), `learning→task` (evidenced-by).

## Usage

```bash
# Build the knowledge graph (no API access needed)
python3 tools/dev-knowledge-graph/ingest.py

# Overlay the conversations cited as evidence (your own, or --all-users for the team)
POSTHOG_PERSONAL_API_KEY=... python3 tools/dev-knowledge-graph/ingest.py \
    --include-conversations --days 14

# Offline from a previously fetched dump
python3 tools/dev-knowledge-graph/ingest.py --include-conversations --from-file out/tasks.json

open tools/dev-knowledge-graph/out/graph.html
```

`ingest.py` is stdlib-only. The viewer supports pan/zoom, search, per-kind filters, a per-user filter, and a detail panel that renders each learning's markdown.

The `out/` directory is gitignored: fetched conversation content is private and must never be committed to this public repo.

## Growing the graph

Add a learning to `learnings.json` when work taught something worth keeping:

```json
{
  "id": "short-kebab-slug",
  "title": "One-line statement of the learning",
  "markdown": "The why, with enough detail that a stranger gets it. Link context: [#66590](https://github.com/PostHog/posthog/pull/66590).",
  "modules": ["frontend/src/lib/components/TaxonomicFilter"],
  "products": ["product analytics"],
  "properties": [],
  "evidence_tasks": [72639, 73819],
  "skills": [{ "name": "adopting-prs", "status": "existing" }],
  "author": "your-name"
}
```

- `markdown` is the knowledge itself — PRs, issues, and docs belong here as links, not as graph nodes.
- `modules` / `products` / `properties` are what the learning is *about*; reuse existing node labels where they fit so knowledge clusters.
- `skills[].status` is `existing` or `proposed` — proposed skills render dashed, so the graph doubles as a backlog of skills worth writing.
- `author` powers the viewer's user filter; match the local part of your email so conversations and learnings share one identity.

The `growing-dev-knowledge-graph` skill (`.agents/skills/`) guides agents through adding learnings at the end of significant work — entries must be public-repo safe (no customer data, internal scale, or Slack quotes).
