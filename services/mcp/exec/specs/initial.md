# Planner brief: code-execution MCP for SDK / OpenAPI

You are a planner agent. Produce an implementation plan for a new MCP server that lets coding agents call an SDK by writing and executing TypeScript code, rather than by invoking one MCP tool per SDK operation. The SDK surface is described by an OpenAPI spec and compiled to TypeScript types via openapi-typescript (or equivalent). Treat the OpenAPI spec as the source of truth and the generated .d.ts as the agent-facing interface.

## Why this exists

The standard "expose every endpoint as an MCP tool" pattern blows up the agent's context window: hundreds of tool schemas get loaded just to make a few calls. This MCP inverts that. The SDK methods are NOT MCP tools — they are library calls inside code the agent writes. The MCP exposes only meta-tools for navigating types, validating snippets, executing them, and inspecting results.

Optimize the design for three scarce resources, in order:

1. Context tokens — never dump the full .d.ts or full API responses into the agent's context.
2. Round trips per task — each tool call is a full LLM turn; one good search beats five narrow ones.
3. Cold-start discoverability — an agent that has never seen this API must be able to orient itself without reading the entire spec.

## Decisions already made (do not relitigate)

- Type format for agents: TypeScript `.d.ts`. Not Zod, not raw JSON Schema. Generated from the OpenAPI spec at server start. Zod (or equivalent) may be used internally for runtime validation if needed, but the agent reads TS.
- Pre-execution validation: `tsc --noEmit` over the generated types. Agents should be able to typecheck a snippet before running it; do not invent a custom validator.
- No per-operation MCP tools. If the planner is tempted to add one, that is a sign the design is drifting back toward the pattern this MCP exists to replace.
- Persistent REPL session, not stateless eval. exec calls share state within a session: variables, imports, and the SDK client persist across calls. This is the single most important decision — it cuts exploration token use by roughly an order of magnitude. Plan around it from the start; do not bolt it on later.

## Tool surface to plan

Five tools. Plan implementation, file layout, dependencies, and edge cases for each.

### 1. search

Single search across three corpora at once: operation names + descriptions, type names + JSDoc, and (optionally) raw spec text. Rank by description matches, not just symbol matches — agents query in natural language, and operation names rarely contain those words. Returns ranked hits with snippets, not full bodies. Calling search with no query returns the index (this subsumes any list_operations tool).

Plan: indexing strategy at server start, ranking function, snippet extraction, pagination.

### 2. read

Polymorphic reader: read({ kind: "type" | "operation" | "tag", name, depth }). For operations, inline the input/output types and any auth/permission requirements so a single read returns everything needed to write the call. Default depth = 1 ref expansion; agent requests more if needed.

Plan: how to resolve transitive type dependencies from the generated .d.ts, how to bound expansion depth, how to format output for token efficiency.

### 3. exec

The core tool. Executes a TypeScript snippet against the SDK with persistent session state. Auto-typechecks first and fails fast. Supports dryRun: true for typecheck-only.

Required output shape:

interface ExecResult {
stdout: string;
stderr: string;
value: unknown; // truncated if large; full value bound to session variable
valueType: string; // e.g. "User[]"
valueShape: ShapeSummary; // keys, types, length for arrays, sample values
durationMs: number;
truncated: boolean;
boundAs?: string; // session variable name if value was truncated
}

Error classification (critical for iteration cost): typecheck error vs. runtime error vs. HTTP 4xx vs. HTTP 5xx vs. network error. For typecheck errors, return file/line/expected/actual + offending span. For HTTP errors, return the request that was sent (sanitized) and the response body. Add a cheap heuristic hint when possible (e.g. "did you mean 'userId'?" for unknown-property errors).

Plan: sandbox choice (Node vm, isolated-vm, Deno permissioned, or subprocess), how typegen + tsc are kept warm across calls, how session state is held (and bounded), how truncation + auto-binding works.

### 4. inspect

Given a session variable name, return its runtime shape — keys, types, sample values, array length — without dumping the full value. The single most useful tool when API responses do not match the spec exactly. Without it agents resort to JSON.stringify(x).slice(0, 2000) and guess.

Plan: shape summarization algorithm, depth limits, handling of cyclic references and large arrays.

### 5. session

Three subcommands:

- session.state — variables in scope with their types, plus current auth/config.
- session.reset — clear all session state.
- session.history — calls made so far with timing and a one-line response summary.

Plan: how state is stored, how history is summarized cheaply, whether sessions are per-MCP-connection or named.

## Cross-cutting requirements

- Truncate by default, expose by reference. Any tool output above roughly 2k tokens is truncated and bound to a session variable. Tell the agent the original size and shape so it can slice into it with a follow-up exec. No tool call should ever be allowed to consume the entire context window.
- Auth lives outside code. Provide a configure({ auth, baseUrl, headers }) mechanism that mutates session state. Do not require the agent to put credentials in snippets — that route leaks secrets into logs, transcripts, and training data.
- Spec version pinning. The MCP must know which version of the OpenAPI spec it is serving and expose it (probably via `session.state`). When the agent's mental model is wrong because of a spec update, the version should be visible.
- GET caching within a session is allowed and probably good. Saves API quota during exploration. Should be invisible to the agent except via session.history.

## Explicitly out of scope

- A standalone typecheck tool — folded into exec via dryRun: true. Two tools that overlap 90% confuse tool selection.
- describe_operation / list_operations — subsumed by search and read.
- Per-operation MCP tools — see decisions above.
- Schema-diff-across-versions tooling — interesting but premature; add only when there is evidence agents hit version-mismatch errors in practice.
- Multi-tenant session sharing across MCP clients — single session per client connection is fine for v1.

## Deliverables from the planner

1. High-level architecture — components, data flow, where the OpenAPI spec is loaded, where typegen runs, where the sandbox runs, where session state lives.
2. File / module layout — concrete paths under src/, following existing project conventions (kebab-case filenames, prefer interfaces over type aliases in TS, OOP where it aids organization).
3. Sandbox decision with tradeoffs — pick one of {Node vm, isolated-vm, subprocess, Deno} and justify against cold-start, isolation, and SDK-import ergonomics.
4. Typegen + tsc warm path — how generated types are cached, how tsc stays warm enough that `exec`'s pre-flight typecheck doesn't dominate latency.
5. Session lifecycle — creation, eviction, memory bounds, what triggers reset.
6. Error taxonomy and shape — concrete TypeScript interfaces for each error class returned by exec.
7. Open questions — anything where the planner had to guess; flag for the user to decide before implementation starts.

Keep the plan concrete: file paths, interface shapes, library choices. Avoid hand-wavy phrases like "we will need to handle X" without saying how. If a decision has more than one reasonable answer, pick one and note the alternative in one line — do not punt.
