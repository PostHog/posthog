# Run-log schemas and query recipes

A run log is JSONL: one JSON object per line, every line has a top-level `type`.
There are two families, depending on which runtime produced the run.
Every recipe below was verified against real logs; copy them as-is and adapt the filters.

Two rules apply to every query:

- Always output with `jq -c` and cap with `head` / string slicing (`[0:300]`) — a single tool
  output can be hundreds of KB.
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
| `turn_completed`          | turn boundary                                                                                                       |

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
jq -c 'select(.event.type=="tool_call_updated" and .event.toolCall.status=="failed") | {line: input_line_number, output: ([.event.toolCall.rawOutput // [] | .[] | .text // ""] | join(" "))[0:300]}' <log>
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

Other useful methods: `_posthog/usage_update` (`params.cost` in USD and `params.used` token
counts, cumulative — `tail -1` is the run's total), `_posthog/turn_complete`.

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
jq -c 'select(.notification.params.update.sessionUpdate=="tool_call_update" and .notification.params.update.status=="failed") | .notification.params.update | {line: input_line_number, title, output: (.rawOutput | tostring)[0:300]}' <log>
```

Agent narration (what the agent said it was doing, and why):

```sh
jq -c 'select(.notification.params.update.sessionUpdate=="agent_message") | {line: input_line_number, text: .notification.params.update.content.text[0:250]}' <log>
```

What the run cost:

```sh
jq -c 'select(.notification.method=="_posthog/usage_update") | .notification.params | {cost, used}' <log> | tail -1
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

Token delta across the span (works on both usage shapes; prints a message when the log
lacks usage updates inside the span — then omit `tokens` from the finding):

```sh
sed -n '<start>,<end>p' <log> | jq -rs '[.[] | select(.notification.method=="_posthog/usage_update") | (.notification.params.usage // .notification.params.used) | select(type=="object") | (.totalTokens // (.inputTokens + .outputTokens + (.cachedReadTokens // 0) + (.cachedWriteTokens // 0)))] | if length > 1 then (last - first) else "insufficient usage updates in span" end'
```

Wasted tool calls are the count of tool-timeline rows between the two lines.

## Evidence quotes

Quote text exactly as jq printed it — copy from your query output, never from memory.
The `report_insight` tool verifies each quote against the raw log (it handles JSON escaping),
and rejects quotes that do not match.
