# Reviewer-quality run — `R2-glm-reviewer`

- **Dumped:** 2026-09-01T00:43:38+00:00
- **Report id:** `01a05a3e-5d07-76b9-8394-3e289f5d3026` · **PR:** https://github.com/PostHog/posthog/pull/75215
- **Head:** `a7fb363bef6947e4e7fc30a0fe8a0a4cc4deaa82` · **run_count:** 1 · **status:** idle
- **Wall-clock:** 2982s (49.7 min)

## Config snapshot

- runtime / model / effort: `claude` / `zai-org/glm-5.3-flash` / `max`
- single-chunk gate / chunk target / soft-max additions = 400 / 300 / 600

## Funnel & cost

| chunks | review units | raw issues | after dedup | passed validator |
| ------ | ------------ | ---------- | ----------- | ---------------- |
| 4      | 6            | 18         | 12          | 0                |

- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy.
- cache-aware spend: no `$ai_generation` events in the window (likely emitted to a cloud project, or not yet ingested).

## Stage timing (wall-clock)

| stage                       | duration |
| --------------------------- | -------- |
| fetch + snapshot            | 0s       |
| chunking                    | 0s       |
| perspective selection       | 14s      |
| review wave (perspectives)  | 24m 31s  |
| blind-spot sweep            | 16m 01s  |
| dedup (incl. combine/clean) | 19s      |
| validation                  | 8m 18s   |

- **Review stage total (selection → last finder unit, wave + blind-spot):** 40m 33s — the reviewer-model speed comparison number.
- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.

## Chunking

- **chunk 1** (8 files): products/review_hog/backend/models.py, products/review_hog/backend/migrations/0019_reviewusersettings_stamphog_review_inbox_prs.py, products/review_hog/backend/api/settings.py, products/review_hog/backend/receivers.py, products/review_hog/frontend/CodeReviewScene.tsx, products/review_hog/frontend/generated/api.schemas.ts, products/review_hog/frontend/generated/api.zod.ts, services/mcp/src/api/generated.ts
- **chunk 2** (8 files): products/stamphog/backend/facade/api.py, products/stamphog/backend/facade/inbox_hooks.py, products/stamphog/backend/tasks/tasks.py, products/stamphog/backend/temporal/activities.py, products/stamphog/backend/logic/reviewer.py, products/tasks/backend/facade/api.py, products/tasks/backend/facade/contracts.py, tach.toml
- **chunk 3** (4 files): tools/pr-approval-agent/review_pr.py, tools/pr-approval-agent/review_local.py, tools/pr-approval-agent/reviewer.py, tools/pr-approval-agent/version.py
- **chunk 4** (2 files): products/stamphog/AGENTS.md, products/stamphog/README.md

## Per-review-unit breakdown

| pass | chunk | perspective                               | raw issues |
| ---- | ----- | ----------------------------------------- | ---------- |
| 1    | 3     | review-hog-perspective-contracts-security | 4          |
| 2    | 1     | review-hog-perspective-logic-correctness  | 5          |
| 2    | 3     | review-hog-perspective-logic-correctness  | 4          |
| 1000 | 1     | review-hog-blind-spots-general            | 2          |
| 1000 | 3     | review-hog-blind-spots-general            | 1          |
| 1000 | 4     | review-hog-blind-spots-general            | 2          |

## Findings (post-dedup) with validator verdict

### [❌ dismissed] consider · documentation — tools/pr-approval-agent/review_pr.py:937-938

**Evidence bundle records that self_driving was set but not why (no task linkage in to_dict)**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** to_dict() adds `"self_driving": self.self_driving` under the comment 'Audit trail for the carve-out: which gates ran relaxed, and why (see **init**)'. The comment promises the 'why' lives in **init**, but the serialized bundle carries only the boolean — the linked task id, the originating Inbox report, and the verifying server are all absent from the evidence record. The CommitProvenance dataclass already has a task_ids field populated from commit-message trailers, but that is author-controlled self-attestation, not the server's linkage decision, and it is serialized separately under 'provenance' rather than next to the self_driving flag. An auditor reading the bundle sees 'self_driving: true' and cannot distinguish a legitimately-linked Inbox PR from a mis-stamped one.
- **Suggestion:** When the hosted runtime supplies the linkage (e.g. a `self_driving_task_id` or `inbox_report_id` key in the context), pass it through to to_dict() alongside the flag so the evidence bundle is self-contained: `"self_driving": self.self_driving, "self_driving_source": context.get("self_driving_review_source")`. Until then, soften the **init** comment to say the 'why' is the server's task-linkage check, which is not currently serialized.
- **Validator:** - **Checked:** the full write path for the engine's `to_dict()` bundle — `tools/pr-approval-agent/review_pr.py:914-962`, the hosted entrypoint `review_local.py:314-359`, the server-side context builder `products/stamphog/backend/logic/reviewer.py:119-132`, and both trigger paths that stamp inbox provenance in `products/stamphog/backend/tasks/tasks.py`.
- **Found:** the linkage the finding calls absent is persisted by the server, in the same record as the engine bundle. Both trigger paths write `{"trigger", "signal_report_id", "task_run_id", "acting_user_id"}` into `ReviewRun.output["inbox_review"]` — receiver leg at `products/stamphog/backend/tasks/tasks.py:1176-1180` and `:1229`, webhook leg at `products/stamphog/backend/tasks/tasks.py:209-213` and `:1064`. The engine's `to_dict()` JSON is later merged into that same `run.output` dict as `reviewer_raw` (`products/stamphog/backend/temporal/activities.py:485-490`). An auditor who reads one `ReviewRun` row therefore sees `self_driving: true` and the task run id, report id, and acting user side by side.
- **Found:** the flag is derived from that stored provenance and from nothing else — `self_driving_review=bool(output.get("inbox_review"))` at `products/stamphog/backend/temporal/activities.py:451`. A `self_driving: true` bundle with no `inbox_review` sibling cannot occur on the hosted path.
- **Found:** the Action path cannot emit `self_driving: true` at all. `main()` builds the pipeline without the keyword (`tools/pr-approval-agent/review_pr.py:984`), so the flag stays `False` for every `--output-json` file the Action writes.
- **Found:** the suggested fix cannot be implemented as proposed. The sandbox context carries only the boolean (`products/stamphog/backend/logic/reviewer.py:131`); no task id reaches the engine. Piping ids into the sandbox so the engine can echo them back would add plumbing for a weaker attestation than the server row already holds, because the engine bundle is sandbox stdout that the server scrubs and stores (`products/stamphog/backend/temporal/activities.py:485-487`).
- **Impact:** no reachable audit gap. What remains of the suggestion is the alternative offered in its own second half — rewording the `(see __init__)` comment at `tools/pr-approval-agent/review_pr.py:937`. That comment points at the design explanation in `__init__` (`tools/pr-approval-agent/review_pr.py:202-208`), which does state why the flag exists, so the pointer is accurate. A comment-wording change with no behavior difference is style, which the criteria drop.

### [❌ dismissed] consider · code_quality — products/review_hog/backend/receivers.py:144-207

**Two reviewers-resolution passes per push: public resolver wraps an identical private helper**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** `resolve_stamphog_acting_reviewer` (lines 144-156) and `_resolve_assigned_reviewer` (lines 159-207) implement the same assignment resolution: both call the artefact lookup, both return `acting.id` under the same fallback rules (creator if assigned, else first resolved reviewer, per the docstring at lines 165-169). The stamphog webhook path calls the public one, which calls the private one, so a single push pays the `SignalReportArtefact` query and the login-to-user mapping twice (once in each layer, plus the third call site at `products/signals/backend/report_generation/resolve_reviewers.py:58`). The layering is not needed for the stated dependency-cycle reason: the private helper already lives in this module, so there is no cycle to break.
- **Suggestion:** Collapse the two into one function: keep `_resolve_assigned_reviewer`'s body, expose it as the single registered resolver via `register_inbox_acting_reviewer_resolver(_resolve_assigned_reviewer)` in `connect()`, and delete the public wrapper. If the public name must remain for the hook's signature, make it a thin `resolve_stamphog_acting_reviewer = _resolve_assigned_reviewer` alias rather than a second implementation.
- **Validator:** - **Checked:** the two functions in full (`products/review_hog/backend/receivers.py:144-207`), every call site of both (`grep` over the repo), the stamphog hook registry (`products/stamphog/backend/facade/inbox_hooks.py`), the webhook consumer (`products/stamphog/backend/tasks/tasks.py:201-215`), and the existing test at `products/review_hog/backend/tests/test_inbox_trigger.py:372-387`.
- **Found:** the two functions are not the same. `resolve_stamphog_acting_reviewer` adds a toggle gate at `receivers.py:154` — it returns `None` when `stamphog_review_inbox_prs` is off. `_resolve_assigned_reviewer` checks no toggle at all; its docstring states this at `receivers.py:160`. The receiver needs the un-gated form, because it calls it once at `receivers.py:111` and then tests two independent toggles separately at `receivers.py:115` and `receivers.py:126`.
- **Found:** there is no repeated work. `resolve_stamphog_acting_reviewer` calls `_resolve_assigned_reviewer` one time at `receivers.py:151`. One push therefore pays one `SignalReportArtefact` query and one login-to-user mapping, not two. The webhook path also calls the resolver once, at `tasks.py:205`.
- **Found:** the claimed "third call site" at `products/signals/backend/report_generation/resolve_reviewers.py:58` is a call to the shared helper `resolve_org_github_login_to_users` inside the Inbox read-time enrichment path. It is not a call to either resolver.
- **Impact:** the premise is mistaken, so the finding does not meet the bar. The proposed fix is also harmful: the alias `resolve_stamphog_acting_reviewer = _resolve_assigned_reviewer` deletes the toggle check, so stamphog would re-review a self-driving PR on later pushes after the user switched the toggle off. That is the exact regression the parameterized test at `test_inbox_trigger.py:372-387` guards against.

### [❌ dismissed] consider · code_quality — products/review_hog/backend/models.py:283-301

**Model TextChoices and serializer ChoiceField share the name `urgency_threshold` for different concerns**  
_perspective: review-hog-perspective-logic-correctness · directly-related: False_

- **Problem:** The model's nested `UrgencyThreshold` TextChoices (models.py:283-287, values 'consider'/'should_fix'/'must_fix') and the serializer's `urgency_threshold` ChoiceField (api/settings.py:39-45, which draws its `choices` from that same TextChoices) both read as 'the urgency threshold'. They are different things: one is the stored preference, the other is the writable API field validating it. Nothing is broken today — the ChoiceField's choices literally reference the TextChoices — but a future edit to either can silently diverge from the other, and grep for `urgency_threshold` returns both.
- **Suggestion:** Leave the behaviour as is, but rename the serializer field to `urgency_threshold_filter` (or similar) in the next schema-touching PR, and add one line to the model docstring stating that `UrgencyThreshold` is the canonical source for the valid values. This is documentation-only; no migration is needed because the DB column keeps the existing name.
- **Validator:** - **Checked:** the model definition (`products/review_hog/backend/models.py:283-301`), the serializer field (`products/review_hog/backend/api/settings.py:39-45`), every `urgency_threshold` / `UrgencyThreshold` reference in the repo, the existing tests, the generated frontend types, and the migration history for the field.
- **Found:** divergence is impossible by construction. The serializer does not copy the values; it references them, at `api/settings.py:41` — `choices=ReviewUserSettings.UrgencyThreshold.choices`. An edit to the model TextChoices flows into the API field automatically. A test also pins the values: `products/review_hog/backend/tests/test_constants.py:30-34` asserts `{c.value for c in ReviewUserSettings.UrgencyThreshold} == {p.value for p in IssuePriority}`.
- **Found:** the two names are not the same. The choices class is `UrgencyThreshold` (models.py:283). The serializer field is `urgency_threshold`, and it must keep that name, because `ReviewUserSettingsSerializer` is a `ModelSerializer` (`api/settings.py:21`, `Meta.model` at line 57) and the name maps it onto the model field `urgency_threshold` (models.py:296).
- **Found:** the field is not part of this pull request. It arrives in migration `0008_reviewusersettings.py:39` and was last altered in `0017_alter_reviewusersettings_urgency_threshold.py`; this pull request adds `0019_reviewusersettings_stamphog_review_inbox_prs.py`. The finding also marks itself `is_directly_related_to_changes: false`.
- **Impact:** the finding states that nothing is broken, and the investigation confirms it. This is a naming preference, which the criteria drop as pure style.
- **Impact:** the suggested rename is also not documentation-only, as claimed. It would change the public API payload key, so it would break the generated types at `products/review_hog/frontend/generated/api.schemas.ts:461` and `:480`, the frontend read at `products/review_hog/frontend/reviewHogSettingsLogic.ts:717`, and the API tests at `products/review_hog/backend/tests/test_settings_api.py:31-117`. It would also need an explicit `source="urgency_threshold"` to keep writing to the model field.

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/receivers.py:220-224

**Deferred imports sit outside the try blocks of the fire-and-forget dispatch helpers, so an import failure escapes the on_commit callback**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** In the new `_start_stamphog_review`, the deferred import `from products.stamphog.backend.facade.api import queue_inbox_pr_review` runs before the `try:` block on line 224. The same shape exists in `_start_review` (imports on lines 254-255, `try:` on line 261). Both helpers run inside `transaction.on_commit` callbacks. Django invokes non-robust callbacks with a bare `func()` call, so an import failure propagates out of the callback into the commit sequence. That breaks the documented invariant that these failures 'must never surface into the saver', and it also aborts any remaining commit hooks. Because the review_hog leg is registered before the stamphog leg, one leg's import failure can silently drop the other leg's dispatch. An import failure is a real trigger here: the deferred modules drag the stamphog model layer and the temporal package onto the import path, which is exactly the code the comments call out as heavy.
- **Suggestion:** Move the deferred imports inside the existing `try:` blocks in both `_start_stamphog_review` and `_start_review`, so every failure path in the callback is covered. Alternatively, register the callbacks with `transaction.on_commit(..., robust=True)`, which isolates a failing callback and keeps the remaining hooks running. The import move is the smaller change and keeps the current log signatures.
- **Validator:** - **Checked:** both dispatch helpers (`products/review_hog/backend/receivers.py:210-234` and `:237-273`), the receiver's own guard (`receivers.py:81-141`), the stamphog facade (`products/stamphog/backend/facade/api.py`), review_hog's URL wiring, and the two production paths that write `TaskRun.output`.
- **Found:** the Django mechanism the finding describes is right, but it never applies on the main path. The agent-server write is `set_task_run_output` at `products/tasks/backend/facade/api.py:2139-2158`, and its `run.save(...)` at `:2154` runs in autocommit — PostHog does not set `ATOMIC_REQUESTS`. In autocommit `transaction.on_commit(func)` calls `func()` inline, so the callback runs inside the receiver's own `try` at `receivers.py:81`, and `except Exception` at `receivers.py:140` catches an `ImportError` like any other error.
- **Found:** the one path that does defer the callback already contains it. The webhook backstop `_record_run_output_field` opens `with transaction.atomic():` at `products/tasks/backend/webhooks.py:286`, but that whole block sits inside its own `try` at `:285` with `except Exception` at `:296`, which logs and returns False. Its docstring at `:277-279` states that a failure there must not fail the webhook. So a raise at commit does not reach the caller and does not surface into the saver.
- **Found:** the import cannot realistically fail in the processes that run this code. `products/review_hog/backend/routes.py:3-10` imports `ReviewUserSettingsViewSet`, and `products/review_hog/backend/api/settings.py:16` imports `products.stamphog.backend.facade.api` at module scope. Any process that loads the URL conf therefore imports that module at boot, so the deferred import at `receivers.py:222` is a `sys.modules` lookup. If the module could not import, the app would fail to start, not degrade one dispatch leg. Stamphog is also unconditionally installed — `posthog/settings/web.py:45`.
- **Found:** the heavy chain the finding points at is already inside a `try`. `queue_inbox_pr_review` defers the GitHub and temporal client imports itself, at `products/stamphog/backend/facade/api.py:144-147`, and review_hog calls that function inside its `try` at `receivers.py:225`. An import failure there is caught today.
- **Impact:** the trigger needs an `ImportError` from a first-party module in an installed app that the same process already imported at startup. That is a broken deploy, not a runtime failure mode. Both real call paths also wrap the commit in an outer handler, so the stated consequence does not occur. This matches the criteria for already-handled and for a practically unreachable edge case.

### [❌ dismissed] consider · best_practice — products/review_hog/backend/api/settings.py:71-81

**A failed stamphog connectivity check is reported and rendered the same as 'not connected'**  
_perspective: review-hog-blind-spots-general · directly-related: True_

- **Problem:** When `has_reviewable_repo_config` raises (for example while the stamphog database circuit breaker is open), `get_stamphog_connected` logs a full traceback at ERROR level and returns False. The settings endpoint is the Code review tab's always-called endpoint, so an outage produces one ERROR traceback per tab load. The False result is then indistinguishable from a genuine 'not connected' state downstream: the frontend (`CodeReviewScene.tsx:1066-1068`) shows a user with a connected repository the message 'Connect a repository to Stamphog first. Stamphog is not set up for this project yet.' and disables the toggle. The log noise makes an expected degradation look like a fault, and the copy asserts a fact the backend could not verify.
- **Suggestion:** Log the handled degradation at WARNING level without the full traceback (or dedupe repeated failures), and keep ERROR for unexpected failures. On the frontend, either keep the disabled state but soften the copy to something that does not assert 'not set up' (for example 'Stamphog is not available right now. Try again in a moment.'), or return a distinct state so the UI can tell an outage from a missing configuration.
- **Validator:** - **Checked:** the handler (`products/review_hog/backend/api/settings.py:71-81`), the facade call it wraps (`products/stamphog/backend/facade/api.py:112-125`), the product-DB circuit breaker config, the frontend switch (`products/review_hog/frontend/CodeReviewScene.tsx:1058-1070`), and every consumer of `stamphog_connected` across the repo.
- **Found:** the case that would actually trap a user is already handled. The `disabledReason` at `CodeReviewScene.tsx:1063-1069` only applies when `!settings.stamphog_review_inbox_prs`. A user who is already opted in keeps an interactive switch during an outage and can still opt out. The inline comment at `:1063-1065` states this intent. The misleading copy therefore reaches only a user who is currently opted out and tries to opt in while the stamphog product DB is down.
- **Found:** the flag drives nothing but this one switch. `stamphog_connected` has no backend consumer — the review dispatch gates on the stored toggle at `products/review_hog/backend/receivers.py:126`, and repo-config gating happens inside the queued Celery task, per the docstring at `receivers.py:215-217`. A failed check therefore cannot cause a wrong review decision, a lost dispatch, or a wrong approval.
- **Found:** the fail-soft is deliberate and documented at `api/settings.py:73-76`, and the raise path opens only while the product-DB circuit breaker is open (`posthog/settings/data_stores.py:172-175`). The state is transient and self-healing: the next tab load after recovery shows the true value.
- **Impact:** the log-level half of this is a taste preference. `logger.exception` on a swallowed exception keeps the traceback, which is what an operator needs when an unexpected exception type appears; the endpoint is a settings-page GET, not a hot path, so the volume is one line per Code review tab load and only while the dependency is down. Dropping the traceback would reduce diagnosability, not improve it.
- **Impact:** the copy half is real but small — imprecise wording on a rare, transient, self-healing degradation, with no correctness, data, contract, or reliability consequence. Under precision over recall this does not clear the bar.

### [❌ dismissed] consider · documentation — products/stamphog/README.md:14-15

**README file attribution for the re-review toggle re-check points at the registering module, not the checking code**  
_perspective: review-hog-blind-spots-general · directly-related: False_

- **Problem:** The added sentence says the webhook path re-checks the toggle 'through `facade/inbox_hooks.py`'. That module only registers the resolver (`register_inbox_acting_reviewer_resolver`, inbox_hooks.py:27); the re-check itself executes in `products/stamphog/backend/tasks/tasks.py` inside `_inbox_rereview_carve_out`, which calls `get_inbox_acting_reviewer_resolver()`. A future reader following the file reference lands on the registry, not the gate.
- **Suggestion:** Reword to 'via the acting-reviewer resolver registered in `facade/inbox_hooks.py` (checked in `tasks/tasks.py::_inbox_rereview_carve_out`)' so the pointer names both the registration site and the enforcement site.
- **Validator:** - **Checked:** `products/stamphog/README.md:14`, `products/stamphog/backend/facade/inbox_hooks.py`, `products/stamphog/backend/tasks/tasks.py:144-212`, `products/review_hog/backend/receivers.py:53-69`, and `products/stamphog/AGENTS.md:80-105`.
- **Found:** The re-check does run through `facade/inbox_hooks.py`. `tasks/tasks.py:25` imports `get_inbox_acting_reviewer_resolver` from that module, and `tasks/tasks.py:201` calls it to obtain the toggle answer. The module is the indirection layer for the check, so the word "through" is literally correct.
- **Found:** The pointer is not a dead end. `facade/inbox_hooks.py:1-13` carries a module docstring that names the caller ("the webhook Celery task calls through the registered callable"), states the fail-closed behavior, and explains why review_hog registers the resolver instead of stamphog importing it. A reader who opens the file gets the full mechanism, not a bare registry.
- **Found:** The same sentence ends with "See AGENTS.md § the self-driving carve-out", and `AGENTS.md:103` repeats the identical phrasing with the registration detail. The README paragraph is a summary that routes the reader to the detailed section by design.
- **Impact:** No behavior changes and no reader is misled to a wrong file. This is a wording preference on a documentation sentence, which the criteria list as pure style/taste to drop. The proposed rewording also adds a second file:line reference that the code can outgrow, so it trades one maintenance point for two.

### [❌ dismissed] consider · documentation — products/stamphog/AGENTS.md:96-99

**Carve-out section's 'two linkage-verified trigger paths' lacks exact anchors**  
_perspective: review-hog-blind-spots-general · directly-related: False_

- **Problem:** The bullet says the hosted server sets the inbox flag exclusively from persisted provenance stamped by 'the two linkage-verified trigger paths'. The two sites are not named: they are the webhook leg and the receiver leg, i.e. the two `output={"inbox_review": inbox_review}` writes at `products/stamphog/backend/tasks/tasks.py:1064` (webhook delivery path) and `products/stamphog/backend/tasks/tasks.py:1229` (`process_inbox_pr_review`). Without the anchors, an auditor cannot confirm 'only two' by reading the code.
- **Suggestion:** Name the two sites inline: '…persisted inbox provenance (`ReviewRun.output["inbox_review"]`, stamped only at `tasks/tasks.py:1064` for the webhook leg and `tasks/tasks.py:1229` for the receiver leg)…', keeping the sentence otherwise as written.
- **Validator:** - **Checked:** `products/stamphog/AGENTS.md:92-105` in full, every `inbox_review` write and read in `products/stamphog/backend/`, and the enclosing function of each write site.
- **Found:** The two stamp sites are real and match the reviewer's claim. `tasks/tasks.py:1064` sits inside `process_pull_request_event` (def at `tasks/tasks.py:810`, the webhook leg) and `tasks/tasks.py:1229` sits inside `process_inbox_pr_review` (def at `tasks/tasks.py:1110`, the receiver leg). No other module writes that key.
- **Found:** The section already names both legs. The next bullet, `AGENTS.md:100-105`, states "The initial review is the receiver leg (`process_inbox_pr_review` …); the webhook leg re-reviews only on synchronize / reopen / base retarget". A reader who reaches the "two linkage-verified trigger paths" phrase gets both names in the following sentence.
- **Found:** The sentence already gives a grep key. `ReviewRun.output["inbox_review"]` at `AGENTS.md:98` locates both writes and all three reads in one search — that is how I confirmed "only two" here.
- **Found:** The suggested fix breaks the file's own convention. Every other pointer in this document uses a symbol reference — `github.py::is_bot_author` (`AGENTS.md:89`), `review_pr.py::_refuse_bot_author` (`AGENTS.md:83`), `logic/approvals.py` (`AGENTS.md:44`). Hard line numbers such as `tasks/tasks.py:1064` go stale on the next edit to that file, so the change would trade a durable pointer for two decaying ones.
- **Impact:** No behavior changes and no auditor is blocked. This is comment wording taste, which the criteria list as noise to drop.

### [❌ dismissed] should_fix · security — tools/pr-approval-agent/review_local.py:321

**self_driving flag is trusted from the context JSON without shape validation**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** run() reads `context.get("self_driving_review")` and coerces it with bool() to arm the carve-out, but never validates that the value is actually a boolean. The flag relaxes two security gates (the bot-author refusal at review_pr.py:225 and the draft prerequisite at review_pr.py:590), so it is the highest-value target in the context payload. If the hosted server ever stamps a non-boolean value (a task-id string, a nested object, or a 'true'/'false' string), any non-empty string is truthy and silently arms the carve-out without the server ever having intended it. The docstring asserts the server 'positively linked' the run to an implementation task, but nothing in the sandbox re-checks that claim — the trust boundary is a comment, not code.
- **Suggestion:** Validate the flag's shape before using it, e.g. `raw = context.get("self_driving_review"); self_driving = raw is True` (strict, fails closed on strings/objects), or validate the whole context against a schema in run() before constructing the Pipeline. Additionally, echo the verified task id (already carried in CommitProvenance.task_ids) into the refusal-path reasoning so an auditor can see which task justified relaxing the gates — right now the REFUSE output says only that the author is a bot, with no provenance.
- **Validator:** - **Checked:** every producer of the `self_driving_review` key, the write path of the context file into the sandbox, how the rest of the context is parsed in `review_local.py`, and whether the suggested provenance echo is reachable on the refusal path.
- **Found:** the key has exactly one producer, and it is already typed and coerced. `products/stamphog/backend/logic/reviewer.py:101` declares `self_driving_review: bool = False`, `:131` writes it straight into the context dict, and the only caller passes `self_driving_review=bool(output.get("inbox_review"))` at `products/stamphog/backend/temporal/activities.py:451`. `json.dumps` of that value emits JSON `true`/`false`, never a string or object. The other runtime (the GitHub Action) never sets the key at all, so it arrives absent and `bool(None)` is `False`. `raw is True` and `bool(raw)` therefore return the same result for every value that can reach `review_local.py:321` today.
- **Found:** no untrusted actor can write the key. The context is a server-side dict literal (`products/stamphog/backend/logic/reviewer.py:119-132`) where PR-controlled content only lands in nested values (`pr`, `files`, `reviews`), so it cannot collide with the top-level flag. The file is written into the sandbox by `_write_context` (`products/stamphog/backend/temporal/activities.py:1123-1131`) before the engine starts, and the engine parses it at `review_local.py:396` before any LLM call. PR-head code never executes in the sandbox — `_harden_reviewer_command` adds `--no-config --no-project` for exactly that reason (`products/stamphog/backend/temporal/activities.py:878-891`).
- **Found:** the singled-out key is parsed the same way as the whole payload. `_build_pr_data` reads `pr`, `base_sha`, `head_sha`, `files`, `reviews`, `pr_reactions`, and `review_threads` with bare `.get()` and duck-typed coercion (`tools/pr-approval-agent/review_local.py:106-166`), including fields that feed the prerequisite gate and the reviewer prompt. Shape-validating one key would not close a reachable hole while that pattern stands.
- **Found:** the second half of the suggestion does not apply to the code it names. The refusal at `tools/pr-approval-agent/review_local.py:324` runs only when `self_driving` is `False`, so no gate was relaxed and there is no task to cite. `CommitProvenance` is never populated on this path either: `self.provenance` is assigned only in `review_pr.Pipeline._fetch` (`tools/pr-approval-agent/review_pr.py:385`), which `review_local` replaces with `_build_pr_data`, so it stays `None`. `task_ids` also come from `Task-Id:` commit-message trailers parsed at `tools/pr-approval-agent/github.py:499-524` — author-written text, not a verified linkage.
- **Impact:** the failure needs a producer that does not exist. It requires a future server change that stamps a truthy non-boolean into the key, which the current typed signature and `bool(...)` call both prevent. That is a speculative what-if against inputs the call sites rule out, which the criteria drop.

### [❌ dismissed] consider · documentation — tools/pr-approval-agent/review_pr.py:202-209,587-590

**Carve-out rationale comment is duplicated verbatim across three files and will drift**  
_perspective: review-hog-perspective-contracts-security · directly-related: True_

- **Problem:** The same 8-line explanation of the self-driving carve-out appears near-verbatim in review_pr.py:202-209, review_local.py:316-320, and reviewer.py:\_format_self_driving's docstring (reviewer.py:683-703). The comment documents the security contract ('relaxes exactly two gates', 'defaults closed', 'engine parity'), so a future edit that updates one copy but not the others leaves the other files describing a contract the code no longer honors. review_local.py:316-320 already differs slightly in wording from review_pr.py:202-209, which is the drift happening in real time.
- **Suggestion:** Keep the authoritative statement of the contract in one place — either the Pipeline.**init** comment in review_pr.py (which is where the flag is actually defined) — and reduce the other two copies to a one-line pointer like 'See review_pr.Pipeline.**init** for the self-driving carve-out contract'. The reviewer.py docstring can keep its unique content (the prompt-rendering rationale) but drop the restated gate list.
- **Validator:** - **Checked:** each of the three comment sites the finding calls near-verbatim duplicates, plus the fourth site it cites as the drift example, and whether a single authoritative statement of the contract already exists elsewhere in the repo.
- **Found:** the blocks are not duplicates; each explains a different local decision. `tools/pr-approval-agent/review_pr.py:202-208` says what the constructor flag is and how far it reaches. `tools/pr-approval-agent/review_local.py:316-320` says where the flag comes from (the hosted context JSON key) and why this entrypoint repeats the bot guard, which is content the `__init__` comment does not carry. `tools/pr-approval-agent/review_pr.py:587-589` gives only the draft-specific reason at the one line that reads the flag for drafts.
- **Found:** the `reviewer.py` docstring does not restate the gate list, so the suggestion's own remedy for it has nothing to remove. `tools/pr-approval-agent/reviewer.py:684-690` covers prompt rendering only — the empty-string default keeping non-carve-out prompts identical, and the swap of human-author trust context for provenance. The words "relaxes exactly two gates" appear nowhere in it.
- **Found:** the shared facts reduce to two short phrases ("defaults closed", "relaxes two gates"), not an eight-line block. The wording difference between `review_pr.py:202-208` and `review_local.py:316-320` is different subject matter at each site, not one copy falling behind another.
- **Found:** a single authoritative statement of the contract already exists outside the engine, in `products/stamphog/CLAUDE.md` under "The self-driving inbox carve-out", which states the same invariants (identification by task linkage, default closed, exactly two relaxed gates, engine parity). The consolidation the finding asks for is already in place at the level where it is enforced for future editors.
- **Impact:** the request changes comment wording only. No behavior, contract, or generated output differs either way, and the risk named is a hypothetical future edit rather than a defect present in the code. The criteria drop pure comment-wording and taste items.

### [❌ dismissed] should_fix · best_practice — products/review_hog/backend/receivers.py:81-141

**Expected 'missing task' condition is logged as an ERROR-level exception on every unrelated TaskRun save**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** In `handle_task_run_saved`, the receiver runs inside the tasks product's save path and fires on every TaskRun save, including saves that have nothing to do with ReviewHog. For a TaskRun whose `task` relation is unset, `instance.task` (line 97) raises `Task.DoesNotExist`, which the broad `except Exception` (line 141) catches and reports via `logger.exception("review_hog_inbox_trigger_failed")`. This is an expected, recoverable condition (a run with no task), yet it emits a full traceback at ERROR level with the same log signature as genuine internal failures. Operations cannot distinguish noise from a real fault, and any alerting keyed on `review_hog_inbox_trigger_failed` fires routinely.
- **Suggestion:** Catch `Task.DoesNotExist` explicitly and return silently (or log at DEBUG/INFO) before the broad handler: `try:\n    task = instance.task\nexcept Task.DoesNotExist:\n    return`. Reserve `review_hog_inbox_trigger_failed` for genuinely unexpected failures. The module docstring (lines 74-77) already promises the body 'must never raise into' the save path, so a controlled early return is consistent with the stated contract.
- **Validator:** - **Checked:** the `TaskRun` model definition, the guard sequence in `handle_task_run_saved`, and the line the finding anchors on.
- **Found:** the premise state cannot exist. `task` is a non-nullable FK — `products/tasks/backend/models.py:1078` declares `task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="runs")` with no `null=True` and no `db_constraint=False`. The column is NOT NULL and the database enforces the reference, so a saved `TaskRun` always has a `Task`. `post_save` fires after the row is written, so `instance.task` at `receivers.py:97` cannot raise `Task.DoesNotExist`. `on_delete=CASCADE` also removes the runs when a task is deleted, so an orphan row is not reachable either.
- **Found:** line 97 does not run on every save. Four guards sit above it: `created` at `receivers.py:82-84`, the `update_fields` check at `:85-89`, the FAILED/CANCELLED check at `:90-91`, and the requirement that `output` carries `pr_url` or `head_branch` at `:92-96`. The comment on line 97 marks it as the "first DB hit" for exactly that reason. Unrelated saves return before it.
- **Impact:** with no reachable trigger, the described log noise does not occur, so alerting on `review_hog_inbox_trigger_failed` does not fire routinely. The suggested `except Task.DoesNotExist` guard would add a branch that no input can reach, which the criteria classify as defensive-coding paranoia.

### [❌ dismissed] consider · code_quality — products/review_hog/backend/receivers.py:126-139

**Dead local alias `stamphog_pr_url = pr_url` obscures the closure capture**  
_perspective: review-hog-perspective-logic-correctness · directly-related: True_

- **Problem:** Inside the stamphog leg, line 130 assigns `stamphog_pr_url = pr_url` solely so the `transaction.on_commit` closure on lines 131-139 can reference a differently-named variable. The alias adds no behaviour: `pr_url` is already bound in the enclosing scope, the closure would capture it directly, and the guard on line 126 guarantees `pr_url` is not None before the block is entered. A reader must stop to work out that `stamphog_pr_url` and `pr_url` are the same value, and the alias suggests a distinction that does not exist.
- **Suggestion:** Remove the alias and reference `pr_url` directly in the closure: `transaction.on_commit(lambda: _start_stamphog_review(pr_url=pr_url, ...))`. The guard on line 126 already ensures the value is safe to capture.
- **Validator:** - **Checked:** the whole receiver body (`products/review_hog/backend/receivers.py:81-141`) for any reassignment of `pr_url` after it is bound, the signatures of both dispatch helpers, and whether a type checker forces the alias.
- **Found:** the alias is behaviorally inert, as the finding says. `pr_url` is bound once at `receivers.py:93` and is never reassigned before or after either `transaction.on_commit` registration, so late binding cannot change what the closure sees. The two lambdas capture the same value either way.
- **Found:** no type checker requires the alias, so the suggested edit is safe but also buys nothing. I reproduced the exact shape — `instance: Any`, `output.get("pr_url") or None`, an `is not None` guard, then a lambda passing the value to a `pr_url: str` parameter — and ran the repo's mypy binary with its strictness flags (`strict_optional`, `no_implicit_optional`, `check_untyped_defs`, `warn_unreachable`, `strict_equality`, Python 3.13). It reports `Success: no issues found`. mypy keeps the narrowed type inside the lambda because the variable is never reassigned. `reveal_type` confirms `Any | None` before the guard and `Any` inside it.
- **Impact:** this is a two-line readability preference with no behavioral difference — the finding states as much. The criteria classify that as pure style, which is not a PostHog Review concern.

### [❌ dismissed] consider · code_quality — tools/pr-approval-agent/review_local.py:321-321

**Pipeline constructed with a hardcoded PR number of 0 in the offline entrypoint**  
_perspective: review-hog-perspective-logic-correctness · directly-related: False_

- **Problem:** `Pipeline(0, ...)` passes 0 as the PR number. Nothing in review_pr.py reads `self.pr_number` — `_capture_review_completed` uses `self.pr.number` from the PRData built from the context, so telemetry is unaffected. But the constructor argument is dead weight and reads as if the offline run is reviewing PR #0.
- **Suggestion:** Pass the real number through: `Pipeline(int((context.get("pr") or {}).get("number") or 0), ...)` — or drop the parameter from the constructor if the field is genuinely never read. Cosmetic.
- **Validator:** - **Checked:** every read of `Pipeline.pr_number` in the engine, the offline entrypoint's construction and error paths, and the PR diff for the flagged line.
- **Found:** `self.pr_number` is read at exactly one place — `tools/pr-approval-agent/review_pr.py:384`, inside `_fetch()`. The offline entrypoint never calls `_fetch()`; it assigns `pipeline.pr = _build_pr_data(context)` directly at `tools/pr-approval-agent/review_local.py:322`. The `0` is therefore inert on every offline path.
- **Found:** no output carries the `0`. Telemetry uses `pr.number` (`tools/pr-approval-agent/review_pr.py:826`), the returned contract uses `self.pr.number` (`tools/pr-approval-agent/review_pr.py:917`), and the crash fallback reads the number back out of the context (`tools/pr-approval-agent/review_local.py:368-370`). All three resolve to the real PR number the server supplied.
- **Found:** the flagged construction predates this PR. The diff for `tools/pr-approval-agent/review_local.py` changes `Pipeline(0, context.get("repo") or "")` to the same call plus the new `self_driving=` keyword — the `0` positional is unchanged existing code, matching the finding's own `is_directly_related_to_changes: false`.
- **Impact:** no wrong result, no failing input, no consequence to name. The finding states no defect and labels its own suggestion "Cosmetic", which places it in the pure style and taste bucket the criteria drop.
