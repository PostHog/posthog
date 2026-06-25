# Tool search: local debugger + why results look irrelevant

`scripts/tool-search-debug.ts` reproduces PostHog MCP tool search **without booting the MCP server**,
so you can see what a query matches and iterate on tool names/descriptions in a tight loop.
This doc also explains why a request like "create a dashboard" can surface completely irrelevant
tools in a coding-agent client.

## TL;DR

When a coding-agent client (Claude Code / PostHog Code) is asked to create a dashboard and its first
move is a "tool search" that returns Notion / Task / Cron / Worktree tools, **that search is the
client's own tool picker, not the PostHog MCP.** Three layers stack up:

1. **Single-exec mode** — for coding-agent clients the server advertises exactly one tool,
   `mcp__posthog__exec`. All ~611 real tools (`dashboard-create`, `insight-create`, …) live behind
   `exec`'s subcommands, so there is no `dashboard-create` for the client to find.
2. **`exec` is undiscoverable** — the client defers `exec` and must search to surface it, but
   `exec`'s advertised description is pure procedure ("Pass CLI-style commands", "Discover tools
   first") with zero product vocabulary. Nothing in it matches "create dashboard insight", so the
   client returns the nearest literal _create_ tools from other connected servers instead.
3. **`exec search` is brittle** — even once `exec` is in hand, `exec search <text>` compiles the text
   as a single case-insensitive **regex**, so `search create dashboard insight` →
   `/create dashboard insight/i` → matches the literal phrase → **0 tools**. You have to search a
   single token (`search dashboard`).

The slowness is the serial round-trips this forces: client tool search → `exec search` →
`exec info` → `exec call`, each a separate model turn and network hop before any real work begins.

## The two "tool searches" — don't conflate them

|                 | Client tool picker                                                           | PostHog `exec search`                                  |
| --------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------ |
| Who runs it     | The coding-agent harness (closed; **not** in this repo)                      | The PostHog MCP server                                 |
| Input shape     | `{ "query": "...", "max_results": N }` → `{ "type": "tool_reference", ... }` | `exec({ "command": "search <regex>" })`                |
| Scope of search | Every connected tool universe (harness builtins + all MCP servers)           | PostHog tools only                                     |
| Algorithm       | Proprietary ranking                                                          | One case-insensitive regex over name/title/description |

The irrelevant `tool_reference` results come from the left column. This script reproduces the right
column — the part we own and can fix. The harness ranking is not in this repo, so it can't be
byte-reproduced here.

## Using the debugger

```bash
cd services/mcp
npx tsx scripts/tool-search-debug.ts "<query>"                       # regex mode (default)
npx tsx scripts/tool-search-debug.ts --mode tokens "<query>"          # candidate ranked search
npx tsx scripts/tool-search-debug.ts --mode both   "<query>" --limit 10
npx tsx scripts/tool-search-debug.ts --json "<query>"                 # machine-readable
```

It loads the real catalog from `schema/tool-definitions-all.json` (the full, **unfiltered** set — no
scope or feature-flag gating — so it shows the upper bound of what a query could match).

- **`regex`** is a faithful copy of the server's `search` predicate (`src/tools/exec.ts:220-262`,
  predicate at line 237): same 200-char cap, same invalid-regex guard, same fields.
- **`tokens`** is a _candidate_ ranked search (not what the server runs today): it splits the query on
  whitespace and ranks tools by a field-weighted score (name 3 > title 2 > description 1) over the
  distinct query tokens they contain.

## The failure, reproduced

```text
$ npx tsx scripts/tool-search-debug.ts --mode regex "create dashboard insight"
▶ regex mode  (exact reproduction of `exec search`)
  pattern: /create dashboard insight/i
  0 matches — the query is tested as one literal regex, so a multi-word phrase rarely matches.
```

A single token works, because it's a substring the regex can find:

```text
$ npx tsx scripts/tool-search-debug.ts --mode regex "dashboard" --limit 8
  33 match(es), showing 8:
    activity-log-list      ← noise: its *description* mentions "dashboard"
    comments-list          ← noise
    dashboard-create
    dashboard-create-text-tile
    dashboard-delete
    ...
```

## What a token-ranked search would surface instead

```text
$ npx tsx scripts/tool-search-debug.ts --mode tokens "create dashboard insight" --limit 6
  207 match(es), showing top 6:
    score  cover matched in         tool
    7      3/3   name+description   dashboard-create
    7      3/3   name+description   dashboard-create-text-tile
    6      2/3   name               dashboard-insights-run
    6      2/3   name               insight-create
    5      3/3   name+description   subscriptions-create
    4      2/3   name+description   action-create
```

The same natural-language query now leads with the tools the agent actually wants. Field weighting is
what keeps `dashboard-create` (tokens in the _name_) above a tool that merely mentions
create/dashboard/insight in prose.

## End-to-end against the real server (this _does_ use the MCP)

To confirm the script matches the served `exec search` path, run the Hono server and call it over
JSON-RPC:

```bash
cd services/mcp
pnpm run dev:hono            # http://localhost:3001/mcp  (needs Redis; set POSTHOG_API_BASE_URL + a Bearer token)

# initialize → grab the Mcp-Session-Id response header, then:
curl -s -X POST http://localhost:3001/mcp \
  -H "Authorization: Bearer phx_..." \
  -H "Mcp-Session-Id: <session-id>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"exec","arguments":{"command":"search dashboard"}}}'
```

The returned tool names match the script's `regex` mode for the same pattern. `pnpm run inspector`
(MCP Inspector GUI) is the point-and-click equivalent.

## Fixing it (out of scope for this debugger)

The debugger exists to iterate on exactly these before committing to a change:

- **Make `exec search` forgiving** — token/relevance ranking (as `tokens` mode prototypes) so
  multi-word intents return the right tools instead of nothing. Lives in the `search` case of
  `src/tools/exec.ts`. The natural first refactor is to extract the predicate into a shared
  `src/tools/tool-search.ts` consumed by both `exec.ts` and this script (kills the copy here).
- **Make `exec` discoverable** — enrich its advertised description
  (`src/templates/sections/exec-tool-blurb.md`, via `buildExecToolDescription` in
  `src/lib/instructions-formatter.ts`) with product vocabulary (dashboards, insights, funnels, flags,
  experiments, error tracking, session recordings, …) so a harness tool search can match it for
  analytics intents — and/or arrange for clients not to defer it.
