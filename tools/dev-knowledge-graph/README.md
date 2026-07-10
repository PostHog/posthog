# Dev knowledge graph

A small graph database + HTML frontend of what we learn while working with agents in this repo: "the system that builds the systems we work on".

It ingests your PostHog Code task history (the conversations you've had with agents), classifies each conversation into themes, links conversations to the PRs they touched, and overlays a hand-curated set of **learnings** and the **skills** (existing or proposed) that encode them. The output is a single self-contained HTML file with a force-directed graph you can pan, zoom, filter, and search.

## Node types

| Kind | Source | Meaning |
| --- | --- | --- |
| `task` | PostHog Code API | One agent conversation |
| `pr` | Extracted from task descriptions | A pull request the conversation worked on |
| `theme` | Keyword classifier in `ingest.py` | A recurring area of work |
| `learning` | `learnings.json` (curated by hand) | Something we learned that should outlive the conversation |
| `skill` | `learnings.json` | A skill that encodes (or should encode) a learning |

Edges: `task→theme`, `task→pr`, `learning→theme`, `learning→task` (evidence), `learning→skill`.

## Usage

```bash
# Fetch your tasks from the last N days and build the graph
POSTHOG_PERSONAL_API_KEY=... python3 tools/dev-knowledge-graph/ingest.py \
    --days 14 --project 2 --repository posthog/posthog

# Include the whole team's conversations (filter by user in the viewer)
POSTHOG_PERSONAL_API_KEY=... python3 tools/dev-knowledge-graph/ingest.py --all-users

# Or rebuild offline from a previously fetched dump
python3 tools/dev-knowledge-graph/ingest.py --from-file /path/to/tasks.json

open tools/dev-knowledge-graph/out/graph.html
```

`ingest.py` is stdlib-only (no pip install). It writes `out/tasks.json` (the raw dump, so later runs can go offline) and `out/graph.html` (the viewer with the graph data embedded).

The `out/` directory is gitignored: task titles and descriptions are private conversation content and must never be committed to this public repo.

## Growing the graph

The interesting half of the graph is `learnings.json`. When a piece of work teaches you something worth keeping, add a learning:

```json
{
  "id": "short-kebab-slug",
  "title": "One-line statement of the learning",
  "body": "The why, with enough detail that a stranger gets it.",
  "themes": ["pr-adoption"],
  "evidence_tasks": [72639, 73819],
  "skills": [{ "name": "adopting-prs", "status": "proposed" }],
  "author": "your-name"
}
```

`evidence_tasks` are PostHog Code task numbers; the ingest links them if they appear in the fetched window. `skills[].status` is `existing` or `proposed` — proposed skills render differently so the graph doubles as a backlog of skills worth writing. `author` powers the viewer's user filter; use the same short name consistently (the ingest derives task authors from the email local part, so matching that keeps one identity per person).

The `growing-dev-knowledge-graph` skill (`.agents/skills/`) guides agents through adding a learning at the end of significant work — learnings must be public-repo safe (no customer data, internal scale, or Slack quotes).
