# Run-log schemas and query recipes

A run log is JSONL: one JSON object per line, every line has a top-level `type`.
There are two families, depending on which runtime produced the run.
The recipes below are backed by runtime tests or verified against real logs; copy them as-is and
adapt the filters.

Two rules apply to every query:

- Cap row listings with `head` and slice large strings (`[0:300]`). Aggregate censuses may scan the
  log because they emit only a small, fixed result.
- `input_line_number` in a jq program gives each match its line number; use it as the anchor
  for context queries.

## Step 1: detect the format

Check the top-level `type` field structurally — never grep the whole line, because log
_content_ (prompts, tool output) can mention the other format's markers:

```sh
jq -r '.type' <log> | sort | uniq -c
```

Any `pi_event` rows → pi format. Otherwise → ACP format. Both formats also contain
`{"type": "notification", ...}` infrastructure lines (console output, progress steps) — those
are shared and mostly noise.
If neither family's recipes below return anything, the log is a format this skill does not
know: go to the failure protocol, do not reverse-engineer it.

## Pi format

Agent events are wrapped as `{"type": "pi_event", "timestamp": ..., "event": {...}}`.
`event.type` is the discriminator:

| `event.type`              | Payload that matters                                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `user_message`            | `event.content[]` — `{type: "text", text}` items                                                                    |
| `assistant_thought_chunk` | `event.content.text` — streaming; thousands of tiny chunks per run, coalesce or skip                                |
| `tool_call_started`       | `event.toolCall`: `id`, `title` (tool name, e.g. `bash`), `kind` (`execute`/`edit`/…), `rawInput` (the actual args) |
| `tool_call_updated`       | `event.toolCall`: `id`, `status` (`completed`/`failed`), `rawOutput[]` (`{type:"text", text}`), `content`           |
| `turn_completed`          | turn boundary; `event.totalTokens` is the completed turn's token total when present                                 |

The tool `title` is terse (`bash`, `write`); the real command is in `rawInput`.

### Pi recipes

Overview — event counts:

```sh
jq -r 'select(.type=="pi_event") | .event.type' <log> | sort | uniq -c | sort -rn
```

Tool timeline with the actual commands:

```sh
jq -c 'select(.event.type=="tool_call_started") | {line: input_line_number, kind: .event.toolCall.kind, title: .event.toolCall.title[0:60], input: (.event.toolCall.rawInput | tostring)[0:150]}' <log> | head -80
```

Failed calls with their output (the primary evidence source):

```sh
jq -c 'select(.event.type=="tool_call_updated" and .event.toolCall.status=="failed") | {line: input_line_number, output: ([.event.toolCall.rawOutput // [] | .[] | .text // ""] | join(" "))[0:300]}' <log> | head -80
```

Status census:

```sh
jq -r 'select(.event.type=="tool_call_updated") | .event.toolCall.status' <log> | sort | uniq -c
```

Largest tool outputs (verbose-output candidates):

```sh
jq -c 'select(.event.type=="tool_call_updated") | {line: input_line_number, bytes: (.event.toolCall.rawOutput | tostring | length)}' <log> | jq -s -c 'sort_by(-.bytes)[0:10][]'
```

## ACP format

Agent events are JSON-RPC notifications: `{"type": "notification", "notification": {"method": ..., "params": ...}}`.
The interesting method is `session/update`, discriminated by `.notification.params.update.sessionUpdate`:

| `sessionUpdate`                         | Payload that matters                                                                     |
| --------------------------------------- | ---------------------------------------------------------------------------------------- |
| `user_message_chunk`                    | `update.content.text`                                                                    |
| `agent_message` / `agent_message_chunk` | `update.content.text` — the agent's narration                                            |
| `agent_thought_chunk`                   | `update.content.text` — streaming thoughts                                               |
| `tool_call`                             | `update`: `toolCallId`, `title` (generic, e.g. `Execute command`), `kind`, `rawInput`    |
| `tool_call_update`                      | `update`: `toolCallId`, `status`, `rawInput` (now populated with real args), `rawOutput` |
| `usage_update`                          | context fill: `used` / `size`                                                            |
| `available_commands_update`             | skills list — huge, skip it                                                              |

Other useful methods: `_posthog/usage_update` (live context/cost updates) and `_posthog/turn_complete`
(some adapters include a finalized `params.usage`).

### ACP recipes

Overview:

```sh
jq -r '.notification.params.update.sessionUpdate // .notification.method // .type' <log> | sort | uniq -c | sort -rn | head -15
```

Tool timeline (join `tool_call_update` for real args — the `tool_call` line's `rawInput` is often empty):

```sh
jq -c 'select(.notification.params.update.sessionUpdate=="tool_call_update") | .notification.params.update | {line: input_line_number, title: .title[0:60], status, input: (.rawInput | tostring)[0:150]}' <log> | head -80
```

Failed calls with output:

```sh
jq -c 'select(.notification.params.update.sessionUpdate=="tool_call_update" and .notification.params.update.status=="failed") | .notification.params.update | {line: input_line_number, title, output: (.rawOutput | tostring)[0:300]}' <log> | head -80
```

Agent narration (what the agent said it was doing, and why):

```sh
jq -c 'select(.notification.params.update.sessionUpdate=="agent_message") | {line: input_line_number, text: .notification.params.update.content.text[0:250]}' <log>
```

Latest completed-turn usage record (use the span recipe below to measure waste):

```sh
jq -c 'select(.notification.method=="_posthog/turn_complete") | .notification.params | {stopReason, usage}' <log> | tail -1
```

## Both formats: context around a finding

Once a query gives you a `line` anchor, read a bounded window around it:

```sh
sed -n '<line-3>,<line+3>p' <log> | jq -c '. | tostring | .[0:400]'
```

## Both formats: measure a wasted span

Bracket the waste with a start and end line number, then measure — never estimate.

Wall-clock seconds between two lines (every line has a top-level `timestamp`):

```sh
sed -n '<start>p;<end>p' <log> | jq -rs '[.[] | .timestamp | gsub("\\.[0-9]+";"") | sub("\\+00:00$";"Z") | fromdateiso8601] | last - first'
```

Tokens consumed by completed turns wholly inside the span. Pi stores the total on `turn_completed`;
some ACP adapters store it on `_posthog/turn_complete`. Do not use live `_posthog/usage_update`
records: they can be repeated snapshots for one turn. The recipe attributes each turn's whole total
by its completion line, so a span that starts or ends mid-turn borrows a full model request from
adjacent work or drops one. Anchor boundaries on turn edges; when the span does not hold complete
turns, or a completion has no usage, omit `tokens`:

```sh
sed -n '<start>,<end>p' <log> | jq -rs 'def token_total: if type == "number" then . elif type == "object" then (.totalTokens // ((.inputTokens // 0) + (.outputTokens // 0) + (.cachedReadTokens // 0) + (.cachedWriteTokens // 0))) else empty end; [.[] | if .type == "pi_event" and .event.type == "turn_completed" then .event.totalTokens elif .notification.method == "_posthog/turn_complete" then (.notification.params.usage | token_total) else empty end | select(type == "number" and . > 0)] | if length > 0 then add else "insufficient completed-turn token records in span" end'
```

Tool-output bytes across the span — works in both formats, even when the log has no token
records. Pi:

```sh
sed -n '<start>,<end>p' <log> | jq -rs '[.[] | select(.event.type=="tool_call_updated") | (.event.toolCall.rawOutput | tostring | length)] | add // "no tool outputs in span"'
```

ACP:

```sh
sed -n '<start>,<end>p' <log> | jq -rs '[.[] | select(.notification.params.update.sessionUpdate=="tool_call_update") | (.notification.params.update.rawOutput | tostring | length)] | add // "no tool outputs in span"'
```

When the same pattern occurs in separate, non-contiguous spans, measure each span with these
recipes and report the sum. Never bracket from the first occurrence to the last — the work in
between is not waste.

### Token-measurement examples

Pi records `totalTokens` with each completed turn. These two complete turns fall inside a measured
span, so the reported token waste is `1200 + 900 = 2100`:

```jsonl
{"type":"pi_event","event":{"type":"turn_completed","totalTokens":1200}}
{"type":"pi_event","event":{"type":"turn_completed","totalTokens":900}}
```

ACP records finalized usage in `_posthog/turn_complete`. Codex provides `usage.totalTokens`; Claude
provides component counts. These two complete turns fall inside a measured span, so the reported
token waste is `800 + (300 + 100 + 150 + 50) = 1400`:

```jsonl
{"type":"notification","notification":{"method":"_posthog/turn_complete","params":{"usage":{"totalTokens":800}}}}
{"type":"notification","notification":{"method":"_posthog/turn_complete","params":{"usage":{"inputTokens":300,"outputTokens":100,"cachedReadTokens":150,"cachedWriteTokens":50}}}}
```

Count distinct tool-call IDs inside the span. ACP emits multiple updates for one call, so counting
timeline rows can over-report waste:

```sh
sed -n '<start>,<end>p' <log> | jq -r 'if .type == "pi_event" and .event.type == "tool_call_started" then .event.toolCall.id elif .notification.params.update.sessionUpdate == "tool_call_update" then .notification.params.update.toolCallId else empty end' | sort -u | wc -l
```

## Evidence quotes

Quote text exactly as jq printed it — copy from your query output, never from memory.
The `report_insight` tool verifies each quote against the raw log (it handles JSON escaping),
and rejects quotes that do not match.
