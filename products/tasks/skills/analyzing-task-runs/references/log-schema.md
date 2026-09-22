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
| `assistant_message_chunk` | `event.content.text` — the agent's narration, streamed in chunks; join a burst to read one message                  |
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

Agent narration, joined per burst (the line is the first chunk of each burst):

```sh
jq -c 'select(.event.type=="assistant_message_chunk") | {line: input_line_number, text: .event.content.text}' <log> | jq -s -c 'reduce .[] as $c ([]; if length > 0 and .[-1].line + 1 == $c.line then .[:-1] + [{line: .[-1].line, text: (.[-1].text + $c.text)}] else . + [$c] end) | .[] | .text |= .[0:250]' | head -40
```

Largest tool outputs:

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

Latest completed-turn usage record:

```sh
jq -c 'select(.notification.method=="_posthog/turn_complete") | .notification.params | {stopReason, usage}' <log> | tail -1
```

## Both formats: context around a line

Once a query gives you a `line` anchor, read a bounded window around it:

```sh
sed -n '<line-3>,<line+3>p' <log> | jq -c '. | tostring | .[0:400]'
```

## Both formats: find split points

Activities start at user turns, at gaps longer than 4 minutes, and at goal changes. The first two
come from the log directly. Every line has a top-level `timestamp`.

User turns with their line numbers. Pi:

```sh
jq -c 'select(.event.type=="user_message") | {line: input_line_number, text: ([.event.content[]? | .text // ""] | join(" "))[0:200]}' <log> | head -40
```

ACP (chunks arrive one per line; take the first chunk of each burst as the turn start):

```sh
jq -c 'select(.notification.params.update.sessionUpdate=="user_message_chunk") | {line: input_line_number, text: .notification.params.update.content.text[0:200]}' <log> | head -40
```

Gaps longer than 4 minutes, with the line that ends each gap:

```sh
jq -r '[input_line_number, (.timestamp // empty)] | @tsv' <log> | python3 -c '
import sys
from datetime import datetime
prev = None
for row in sys.stdin:
    line, ts = row.rstrip("\n").split("\t")
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if prev is not None and (t - prev).total_seconds() > 240:
        print(line, int((t - prev).total_seconds()), "s")
    prev = t
' | head -40
```

Line ranges for the tool timeline give you the goal changes. Read the commands in order and mark
the line where the agent moves from one goal to the next.

## Both formats: reach the end of the log

Every recipe above caps its rows with `head`. Get the line count first:

```sh
wc -l <log>
```

When a recipe returns its full cap, continue from the last line you saw instead of raising the cap:

```sh
tail -n +<last line seen + 1> <log> | jq -c '...same filter..., line: (input_line_number + <last line seen>)' | head -80
```

Stop only when the last line you have seen is the last line of the log. The final activity ends on
that line.

## Evidence quotes

Quote text exactly as jq printed it. Copy from your query output, never from memory.
The `report_activity` tool verifies each quote against the raw lines inside your range (it handles
JSON escaping), and rejects quotes that do not match or that fall outside the range. When a
`blocker_kind` is set, the quote must also contain `blocker_name` as a whole word.
