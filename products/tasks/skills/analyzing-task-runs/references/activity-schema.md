# Activity record schema

One `report_activity` call records one activity. You supply nine fields. The tool computes the
rest from the log lines you name and sends the whole record to the server.

## Fields you supply

| Field          | Type           | Rule                                                                                  |
| -------------- | -------------- | ------------------------------------------------------------------------------------- |
| `goal_kind`    | enum           | Which kind of work the agent did. See the table below.                                |
| `goal`         | string, 3–80   | What the agent tried, in 3 to 8 words. Name the object: "run the backend tests".      |
| `outcome`      | enum           | `worked`, `failed`, `abandoned`, or `unknown`.                                        |
| `blocker_kind` | enum, optional | What stopped the agent. Omit for healthy work. See the table below.                   |
| `blocker_name` | string, 1–120  | Required with `blocker_kind`. The exact name the log uses. Must appear in `evidence`. |
| `repair`       | string, 1–300  | Optional. The command or step that removed the blocker.                               |
| `evidence`     | string, 10–200 | One exact quote from the log, inside the line range. Copy it from your jq output.     |
| `start_line`   | integer ≥ 1    | First log line of the activity.                                                       |
| `end_line`     | integer ≥ 1    | Last log line of the activity. Not before `start_line`.                               |

## Fields the tool computes

From the lines in `[start_line, end_line]`:

- `tool_calls`: distinct tool calls that started in the range.
- `failed_calls`: those calls whose last status is `failed`.
- `seconds`: wall clock from the last timestamp before the range to the last timestamp in the range. Activities partition the run, so the gap before an activity counts toward it.
- `idle_seconds`: the sum of gaps longer than 4 minutes inside that span, including the gap before the first line.
- `commands`: the ordered command heads the agent ran (`git commit`, `pytest`, `pnpm test`), deduplicated when consecutive, at most 24. A shell line with `&&`, `|`, or `;` yields one head per part.
- `guidance_read`: skills, `AGENTS.md`, `CLAUDE.md`, PR template, and wiki pages the agent read, whether through a shell command, a file-read tool, or a skill tool. A skill appears as `skill:<name>`.

You do not estimate these. Get the line range right and the numbers follow.

## `goal_kind`

| Value       | The agent was...                                                                  |
| ----------- | --------------------------------------------------------------------------------- |
| `orient`    | reading task instructions, skills, `AGENTS.md`, or wiki pages before it acted     |
| `explore`   | reading code to understand how something works                                    |
| `gather`    | pulling data from outside the repo: PostHog queries, API calls, issue trackers    |
| `produce`   | writing or editing code, tests, docs, or config                                   |
| `verify`    | running tests, type checks, lint, or a build to check its own work                |
| `setup_env` | installing tools, starting services, building dependencies, so other work can run |
| `ship`      | committing, pushing, opening or updating a pull request                           |
| `wait`      | polling or sleeping for something outside its control: CI, a service, a human     |
| `operate`   | acting on a live system that is not the repo: dashboards, flags, deploys          |
| `deliver`   | writing its final answer, summary, or artifact for the user                       |

## `outcome`

| Value       | Meaning                                                                   |
| ----------- | ------------------------------------------------------------------------- |
| `worked`    | The agent reached the goal, with or without a repair on the way.          |
| `failed`    | The agent tried, could not reach the goal, and moved on or stopped.       |
| `abandoned` | The agent stopped trying without a clear failure, often after a redirect. |
| `unknown`   | The log does not show how the activity ended.                             |

## `blocker_kind`

Use a blocker only when something outside the agent's own code stopped a step. A test that fails
because of the agent's edit is not a blocker.

| Value                    | `blocker_name` is...                                         | Example name               |
| ------------------------ | ------------------------------------------------------------ | -------------------------- |
| `missing_binary`         | the binary that was not found                                | `gh`                       |
| `missing_package`        | the package or module that could not be imported or resolved | `@posthog/shared`          |
| `service_down`           | the service or port that refused a connection                | `port 5432`                |
| `missing_build_artifact` | the file or directory that had to be built first             | `dist/index.js`            |
| `missing_credential`     | the token, key, or login that was absent                     | `GH_TOKEN`                 |
| `memory_limit`           | the process that was killed or ran out of memory             | `tsc`                      |
| `network`                | the host or URL that did not respond                         | `registry.npmjs.org`       |
| `shallow_git`            | the git operation that failed on a shallow or detached clone | `git merge-base`           |
| `tool_error`             | the tool that returned an error unrelated to its input       | `Edit`                     |
| `tool_syntax`            | the tool the agent called with a malformed input             | `jq`                       |
| `api_error`              | the API or endpoint that returned an error                   | `/api/projects/2/insights` |
| `missing_flag`           | `<command head> <flag>` the command did not accept           | `hogli test --changed`     |
| `unclear_instructions`   | the instruction, file, or skill that sent the agent wrong    | `AGENTS.md`                |
| `user_redirect`          | the user, when the user changed the goal mid-activity        | `user`                     |

`blocker_name` must appear in `evidence`, case-insensitive. Pick the quote first, then name the
blocker from it.

## Splitting rules

- Start a new activity when the user speaks, when more than 4 minutes pass with no event, or when
  the agent moves to a new goal.
- A user message that changes the goal is the last line of the activity it interrupts. The next
  activity starts on the line after it.
- Merge small steps that serve one goal. Ten `Read` calls that map one module are one `explore`
  activity.
- Keep between 1 and 12 activities. Most runs fit in 3 to 8. With more than 12 boundaries, merge
  adjacent activities that share a `goal_kind`, shortest first, until 12 remain.
- Activities do not overlap, they arrive in log order, and together they cover line 1 to the last
  line of the log. The tool rejects a range that starts at or before the previous `end_line` and
  a range that ends past the last line, and names the line to use instead.
- An empty or unreadable log gets one `deliver` activity with outcome `unknown` and goal
  `empty log` on lines 1 to 1.

## Worked example

A run log where the agent read the repo guide, edited a serializer, ran the tests twice (the
first run hit a database that was not up), and opened a PR that failed because `gh` was missing.
Four calls, in this order:

```json
{
  "goal_kind": "orient",
  "goal": "read the repo guide and task",
  "outcome": "worked",
  "evidence": "cat AGENTS.md",
  "start_line": 1,
  "end_line": 14
}
```

```json
{
  "goal_kind": "produce",
  "goal": "add the export field to the serializer",
  "outcome": "worked",
  "evidence": "Edit products/exports/backend/serializers.py",
  "start_line": 15,
  "end_line": 41
}
```

```json
{
  "goal_kind": "verify",
  "goal": "run the export serializer tests",
  "outcome": "worked",
  "blocker_kind": "service_down",
  "blocker_name": "port 5432",
  "repair": "docker compose up -d db",
  "evidence": "connection to server at \"localhost\", port 5432 failed",
  "start_line": 42,
  "end_line": 77
}
```

```json
{
  "goal_kind": "ship",
  "goal": "open the pull request",
  "outcome": "failed",
  "blocker_kind": "missing_binary",
  "blocker_name": "gh",
  "evidence": "gh: command not found",
  "start_line": 78,
  "end_line": 96
}
```

The tool replies with the computed numbers for each call, for example
`Recorded activity 3 (verify, worked) for lines 42-77 of 96: 6 tool calls, 1 failed, 402s, 0s idle. 9 more allowed; merge adjacent activities with the same goal_kind if the run needs more.`

## Errors the tool returns

- A range or field error names the rule and the value to use. Fix that field and call again.
- `Activity K already covers lines a-b` means the range overlaps a recorded activity. Use the
  `start_line` the message names.
- `end_line N is past the end of the log` means the range runs past the last line. Use `wc -l`.
- `The activity was rejected by the server` means the server refused the record. Correct the
  flagged field and call again.
- `The activity report did not complete` means the call did not reach a server answer. Call again
  with the same arguments; the server ignores an exact repeat.
