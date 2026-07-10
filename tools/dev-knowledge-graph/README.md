# Dev knowledge graph

A mind map of the PostHog system and what we learn while working on it: "the system that builds the systems we work on".

The top level is **concepts** — the nouns two people working together would use ("the taxonomic filter", "the dashboards API", "the event pipeline") — color-coded by system area and drillable: click a concept to open what's inside it (sub-concepts and learnings), click again to back out. Learnings carry inspectable markdown; PRs and conversations appear as links inside that markdown, not as nodes.

## Structure

| Piece     | File             | Meaning                                                                                                                  |
| --------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Layers    | `concepts.json`  | System areas that color-code the map (frontend app, main Django app, ingestion services, CI & repo tooling, agent fleet) |
| Concepts  | `concepts.json`  | The system's nouns, in a hierarchy — each with markdown describing what it is and how data flows through it              |
| Learnings | `learnings.json` | What work taught us, attached to the concepts it's about; markdown with PRs/conversations as links                       |
| Skills    | `learnings.json` | The skill that encodes a learning (`existing`) or should (`proposed`, rendered dashed)                                   |
| Tasks     | API overlay      | Conversations cited as evidence — only with `--include-conversations`                                                    |

## Usage

```bash
# Build the mind map (no API access needed)
python3 tools/dev-knowledge-graph/ingest.py

# Overlay the conversations cited as evidence (your own, or --all-users for the team)
POSTHOG_PERSONAL_API_KEY=... python3 tools/dev-knowledge-graph/ingest.py \
    --include-conversations --days 14

open tools/dev-knowledge-graph/out/graph.html
```

`ingest.py` is stdlib-only. The viewer: click concepts to drill in and back out (the `+N` badge shows how much is inside), drag nodes, scroll to zoom, search (reveals matches inside collapsed concepts), filter by system area, knowledge kind, and user.

The `out/` directory is gitignored: fetched conversation content is private and must never be committed to this public repo.

## Growing the map

Two kinds of contribution, both guided by the `growing-dev-knowledge-graph` skill (`.agents/skills/`):

**A concept** (`concepts.json`) when the map is missing a part of the system you had to understand to do the work — write the markdown as you'd explain it to a teammate: what it is, how data flows, the constraints that bite.

```json
{
  "id": "recordings-list-query",
  "name": "Recordings list query",
  "layer": "django",
  "parent": "session-replay",
  "markdown": "What it is, how data flows through it, what constraints matter."
}
```

**A learning** (`learnings.json`) when work taught something worth keeping, attached to the concepts it's about:

```json
{
  "id": "short-kebab-slug",
  "title": "One-line statement of the learning",
  "markdown": "The why, with context as links: [#66590](https://github.com/PostHog/posthog/pull/66590).",
  "concepts": ["taxonomic-search"],
  "evidence_tasks": [72639, 73819],
  "skills": [{ "name": "adopting-prs", "status": "existing" }],
  "author": "your-name"
}
```

Both files are committed to a public repository — no customer data, internal scale, or Slack quotes. `author` powers the per-user filter; match the local part of your email.
