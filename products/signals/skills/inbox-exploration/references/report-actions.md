## Workflow: run an action on a report

A report can offer actions that start an agent run, the same ones the inbox shows as buttons:
**Get it merged** (`get_it_merged`) fixes CI on the report's open, approved pull request and merges
it, **Make it green** (`make_it_green`) fixes failing CI on its open pull request without merging,
and each **suggested prompt** (`suggested_prompt`) sends one prompt the report suggests. **Ask**
(`ask`) sends your own `message`, like Ask AI in the inbox. Use these instead of
`tasks-create-and-run`: a run started here is linked to the report, so it shows in
the report's runs, counts toward the report's task limit, and gets the report's code access rules.
The two tools are rolling out behind a flag, so they can be missing from your tool list. If they
are, send the person to the report's `_posthogUrl` to press the button.

### Step 1 — List the actions

```json
posthog:inbox-report-actions-list
{ "report_id": "<report_uuid>" }
```

Every action comes back, available or not. Pick one with `available: true`. When an action is not
available, `disabled_reason` says why (no approved open PR, AI data processing not approved, and so
on): tell the person rather than trying to run it. `text` is the message the run gets as its first
request, so show it when the person wants to know what the agent will be asked to do.

### Step 2 — Confirm, then run it

Starting a run creates a task that spends the organization's usage, and Get it merged can merge a
pull request. Confirm with the person before you run an action they did not ask for by name.

```json
posthog:inbox-report-actions-run
{ "report_id": "<report_uuid>", "action": "suggested_prompt", "suggested_prompt_index": 0 }
```

Pass `suggested_prompt_index` only for `suggested_prompt`, with the value from the list.

To ask about the report or request work the listed actions do not cover, use `ask` with a
`message`. `ask` is not in the list. The run answers a question, and carries out requested work
only while the report still has work to do and no pull request:

```json
posthog:inbox-report-actions-run
{ "report_id": "<report_uuid>", "action": "ask", "message": "Which customers hit this error?" }
```

`get_it_merged` and `make_it_green` also take an optional `message`. It replaces the action's
fixed request and keeps its instructions and gates. Pass it only when you know something the report
does not, such as "#123 lands first, so rebase onto it after it merges" or "the migration check
also fails on the base branch, so leave it".

A `201`
returns `task_id`, `run_id`, and `task_url`. Each successful call creates a new task, so do not
retry it. If `run_error` is set, the task exists but its run did not start: report the error and do
not start a second one.

### Step 3 — Follow the run

The run works in the background. Follow it with `tasks-runs-retrieve` using `task_id` and `run_id`,
and give the person `task_url`. Nobody can answer questions in a background run, so when the agent
needs a decision it writes a note to the report's work log. Read new notes with
`inbox-report-artefacts-list`.

### Errors

Every refusal carries a `code`. Do not retry any of them unchanged.

| Status | `code`                              | What to do                                                                                      |
| ------ | ----------------------------------- | ----------------------------------------------------------------------------------------------- |
| 400    | `report_action_unavailable`         | The action is not available now. Tell the person the `detail`.                                  |
| 403    | `report_action_unavailable`         | The organization has not approved AI data processing. An admin turns it on in settings.         |
| 403    | `report_action_sandbox_refused`     | A task sandbox cannot start report actions. Ask a person to start it from their own session.    |
| 409    | `report_action_run_active`          | A merge run is already working on the report. Follow the `task_id` and `run_id` in the body.    |
| 429    | `signal_report_task_cap`            | The report reached its task limit. Work with the runs it already has.                           |
| 429    | `throttled`, `usage_limit_exceeded` | A per-user or organization usage limit fired. Wait until it clears.                             |
| 402    | `self_driving_free_trial`           | The organization is on a Self-driving free trial, which cannot open pull requests.              |
| 404    | none                                | The report has no suggested prompt at that index. List the actions again and use a fresh index. |

## Workflow: file a report

Use `inbox-reports-create` when the user wants a finding of their own, often from their own
agent, to land in the inbox. The tool is behind a rollout flag, so it is not always present.

1. Search first. Call `inbox-reports-search` with a `query` for the topic, and search again in other words
   before you decide nothing matches. When that tool is not present, call `inbox-reports-list` with `search`.
   If a report already covers it, tell the user and work on that report instead of filing a near-duplicate.
2. Send `title`, `summary`, at least one `evidence` entry, `actionability`, and
   `actionability_explanation`. Add `suggested_reviewers` to route it to the people who should read it.
3. Read the result. `report_status` is `ready`, `pending_input`, or `suppressed`. A suppressed report
   carries `safety_explanation`. A resend returns the first report with `idempotent_replay` true.

A filed report never starts an implementation run or opens a pull request on its own, even after a
later edit. To start one, use [report actions](report-actions.md). Each person can file 20
reports per project per day. A 429 says when the limit resets.
