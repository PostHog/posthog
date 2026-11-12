## Workflow: resolve, dismiss, or snooze a report

Three outcomes, one tool. Pick by what actually happened to the underlying issue:

| The issue is…                                 | State        | Why                                                |
| --------------------------------------------- | ------------ | -------------------------------------------------- |
| fixed by work you did                         | `resolved`   | terminal; the report has served its purpose        |
| not real, or not worth fixing                 | `suppressed` | dismissed from the inbox, with the reason recorded |
| real but deferred, or fixed by something else | `potential`  | back into the pipeline; reappears if it recurs     |

```json
inbox-reports-set-state
{
  "id": "<report_uuid>",
  "state": "suppressed",
  "dismissal_reason": "analysis_wrong",
  "dismissal_note": "Verified against products/foo/bar.py — the cited code path can't reach this state."
}
```

- `state: "resolved"` marks the requested work done, and is terminal — a recurrence starts a fresh
  report rather than reopening this one. Allowed from `ready`, `pending_input`, `failed`, `monitoring` or `closed`,
  or from a `suppressed` report that held one of those when archived; anything else returns `409`. **Only
  resolve work that has actually landed.** A fix shipping as a PR resolves itself on merge, or enters `monitoring` (see
  [Implementation step 4](implementation.md#step-4--open-the-pr-and-attach-it)); resolve by hand only where the webhook can never reach — a skill-body edit, a config
  change, a `NO_REPO` report. Record `dismissal_reason: "fixed_outside_posthog"` for that (the fix
  landed without a pull request); use `pr_merged` when a pull request with the fix was merged but
  did not resolve the report on its own; reserve `already_fixed` for an issue fixed before the
  report was filed. Don't use `already_fixed` + `state: "potential"` when _you_ did the fixing:
  that pairing means "fixed by something else, might recur", so the report comes back.
- `state: "suppressed"` dismisses the report from the inbox; `state: "potential"` snoozes it back
  into the pipeline. When snoozing, `snooze_for: <N>` holds it until it accumulates N more signals.
- `dismissal_reason` must be one of the server-validated canonical codes — `already_fixed`,
  `report_unclear`, `analysis_wrong`, `wrong_assignee`, `wrong_repo`, `wontfix_intentional`,
  `wontfix_irrelevant`, `fixed_outside_posthog`, `verified_manually`, `no_action_needed`, `pr_merged`, `other` — an
  unlisted value returns `400`. Reach for `other` plus a
  `dismissal_note` for anything that doesn't fit a specific code. `dismissal_note` is free-form
  (≤ 4000 chars). Both persist as a DISMISSAL
  artefact, so the rationale survives later transitions — **always include them**, on a resolve too,
  so a future reader knows _why_.
- `wrong_repo` means the agent researched the report against the wrong repository. Pair it with
  `corrected_repository` (`"owner/repo"`, case-insensitive; only allowed with this reason) naming
  the right one: the correction is recorded on the dismissal and fed into every future repository
  selection for the project, and when the named repository is connected to the project it also
  becomes this report's own next selection. Without a usable correction the report's selection is
  cleared instead, so a restored report re-selects rather than reusing the rejected repository.
- A `wrong_repo` correction fixes one report.
  When a whole kind of request keeps going to the wrong repository, a repo routing rule is the project-wide lever:
  it maps a kind of request to the repository that owns it, and the repository selector reads it for every task and report.
  Read the rules with `inbox-repo-routing-rules-list` first, to see if one should have applied or now sends work to the wrong place.
  Then fix that rule with `inbox-repo-routing-rules-update`, or add one with `inbox-repo-routing-rules-create`.
  Confirm with the user before a rule change, because it moves teammates' future work too.
- `wrong_assignee` means the report reached the wrong person or team. It is routing feedback, not a
  verdict that the report itself was wrong.
- On a dismiss, snooze, or restore, the `dismissal_note` is also forwarded as a steering note to the
  scout that filed the report, which every scout run reads at cold start, so what you write there is
  what stops the same report being filed again. Write it for that reader: name the evidence that
  settles it, not just the verdict. A resolve is not forwarded, since it says the report did its job
  rather than that filing it was wrong; that note stays on the report. A `wrong_repo` dismissal is
  forwarded even with no note: the steering note names the repository the report wrongly targeted
  and, when you passed one, the `corrected_repository`. Forwarding needs the same skill-editing
  access as leaving a scout note by hand, so on a project where you lack it the note still lands on
  the report but does not reach the scout.
- It's a destructive, non-idempotent transition and returns `409` if it isn't allowed from the
  report's current status (and `400` if `dismissal_reason` isn't a canonical code). Confirm with
  the user before suppressing, and capture _why_ in the note — a dismissal with no rationale is
  worse than none. A report you dismissed because the diagnosis was wrong ([Implementation step 2](implementation.md#step-2--verify-the-diagnosis-against-the-code-do-not-skip)) is the
  textbook case: suppress it with `analysis_wrong` and the evidence in the note. A refunded report
  is frozen: snooze and resolve both come back `409` / `skipped` with an explanatory `detail`.
- To transition several reports at once, use `inbox-reports-bulk-set-state` with an `ids`
  array (1–100). It applies the same `state` / `dismissal_reason` / `dismissal_note` /
  `corrected_repository` / `snooze_for` to every id and returns a per-id `results` list (in request
  order) plus a
  `transitioned_count` / `skipped_count` / `failed_count` / `not_found_count` summary. Each id is
  processed independently, so the call returns `200` even on partial failure — an id whose
  transition isn't allowed comes back as `skipped` (the single-report `409`) while the rest go
  through. Inspect the per-id outcomes rather than assuming the whole batch succeeded.

## Monitoring

Where the organization has Monitoring on, a report whose fix shipped is verified before it resolves.
Its follow-up checks measure whether the fix worked over a fixed window that starts when the fix ships.
Without open follow-up checks, the report resolves directly.

- A report enters `monitoring` when its linked PRs complete with at least one merged.
  `inbox-reports-set-state` with `state: "monitoring"` does the same for a fix that landed without a linked PR.
- The checks' verdicts decide the outcome: all passing resolves the report, and a failure closes it.
  When the evidence is inconclusive, an assessment reads it and decides.
- A `closed` report did not show that the fix worked.
  A linked follow-up report researches why.
- Read progress with `inbox-reports-list` (`view: "monitoring"`, then each row's `monitoring_summary`)
  and with `inbox-report-checks-list` (each check's `monitoring_timing`).
  Interim readings and verdicts are `check_observation` and `check_result` entries in `inbox-report-artefacts-list`.
- To end verification by hand, resolve the report with `verified_manually`, `no_action_needed` or `already_fixed`,
  and say in `dismissal_note` what you checked. This stops the remaining checks.
- `state: "ready"` reopens a report in `monitoring` or `closed`, keeping its research, pull requests and checks.
  Completing the implementation again starts a new Monitoring period only if the report still has open follow-up checks.
  A report reopened from `closed` has none, because closing ends every check, so its next completion resolves it without verification.
  Tell the user before promising that a new fix will be verified.
- To measure a check better, replace it with a metric check through `inbox-report-checks-replace`.
  Replacing a check during Monitoring restarts the period for every open check.
