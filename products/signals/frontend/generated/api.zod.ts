/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * View and control signal processing pipeline state for a team.
 */
export const SignalsProcessingPauseUpdateBody = /* @__PURE__ */ zod.object({
    timestamp: zod.iso
        .datetime({ offset: true })
        .describe('Pause the grouping pipeline until this timestamp (ISO 8601).'),
})

/**
 * Edit the human-facing title and/or summary (description) of a signal report, addressed by id. Both fields are optional — supply only the ones you want to change; at least one is required. Every other report field (status, weights, judgments) is managed by the signals pipeline and cannot be set here. Returns the full updated report.
 * @summary Edit a report's title or summary
 */
export const signalsReportsPartialUpdateBodyTitleMax = 300

export const signalsReportsPartialUpdateBodySummaryMax = 10000

export const SignalsReportsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        title: zod
            .string()
            .min(1)
            .max(signalsReportsPartialUpdateBodyTitleMax)
            .optional()
            .describe('New human-facing title for the report. Omit to leave the title unchanged.'),
        summary: zod
            .string()
            .min(1)
            .max(signalsReportsPartialUpdateBodySummaryMax)
            .optional()
            .describe(
                "New summary (the report's description) explaining what the report is about. Omit to leave the summary unchanged."
            ),
    })
    .describe(
        'Editable human-facing fields on a signal report (PATCH).\n\nBoth fields are optional so a caller can change either independently, but at least one\nmust be supplied. Every other report field — status, weights, judgments — is owned by the\nsignals pipeline and is deliberately not writable here.'
    )

/**
 * Record the thumbs rating at the end of a report, with an optional note. For browser-session requests the rating is persisted as a per-person report action, which counts as consumption evidence for the scout that authored the report (scouts whose output nobody consumes are eventually paused); requests authenticated any other way record no action. When a note is present and the report was authored by a scout, the note is also forwarded to that scout as a steering note it reads on its next run; for any other report there is nothing to steer. The report's state is never changed.
 * @summary Leave feedback on a report
 */
export const signalsReportsFeedbackCreateBodyNoteDefault = ``
export const signalsReportsFeedbackCreateBodyNoteMax = 4000

export const SignalsReportsFeedbackCreateBody = /* @__PURE__ */ zod.object({
    sentiment: zod
        .enum(['positive', 'negative'])
        .describe('\* `positive` - positive\n\* `negative` - negative')
        .describe(
            "The rating left on the report: 'positive' (thumbs up) or 'negative' (thumbs down).\n\n\* `positive` - positive\n\* `negative` - negative"
        ),
    note: zod
        .string()
        .max(signalsReportsFeedbackCreateBodyNoteMax)
        .default(signalsReportsFeedbackCreateBodyNoteDefault)
        .describe(
            'Free-form note explaining the rating. Capped at 4000 characters. Optional — a bare thumb carries none. When present and the report was authored by a scout, the note is forwarded to that scout as a steering note.'
        ),
})

/**
 * Post an inline review comment on the report's implementation pull request, attributed to the requesting user's own GitHub identity via their personal GitHub connection. Either replies to an existing thread (`in_reply_to`) or starts a new thread on a diff line (`path` + `line`).
 * @summary Post an inline review comment on a report's implementation PR
 */
export const signalsReportPrReviewCommentsCreateBodyBodyMax = 65536

export const signalsReportPrReviewCommentsCreateBodyInReplyToRegExp = new RegExp('^[0-9]+$')

export const SignalsReportPrReviewCommentsCreateBody = /* @__PURE__ */ zod
    .object({
        body: zod
            .string()
            .max(signalsReportPrReviewCommentsCreateBodyBodyMax)
            .describe('Comment body (GitHub-flavored markdown).'),
        in_reply_to: zod
            .string()
            .regex(signalsReportPrReviewCommentsCreateBodyInReplyToRegExp)
            .nullish()
            .describe('Numeric id of the thread root comment to reply to. When set, path\/line\/side are ignored.'),
        path: zod
            .string()
            .nullish()
            .describe('File path to anchor a new comment thread to (required when starting a new thread).'),
        line: zod
            .number()
            .min(1)
            .nullish()
            .describe('Diff line to anchor a new comment thread to (required when starting a new thread).'),
        side: zod
            .union([zod.enum(['LEFT', 'RIGHT']).describe('\* `LEFT` - LEFT\n\* `RIGHT` - RIGHT'), zod.null()])
            .optional()
            .describe(
                "Diff side of the anchor line: 'LEFT' = deletions, 'RIGHT' = additions. Defaults to 'RIGHT'.\n\n\* `LEFT` - LEFT\n\* `RIGHT` - RIGHT"
            ),
    })
    .describe(
        'Request body for posting an inline PR review comment as the requesting user.\n\nTwo shapes: a reply to an existing thread (only `body` + `in_reply_to`), or a new\nthread on a diff line (`body` + `path` + `line`, optionally `side`).'
    )

/**
 * @summary Edit one of the requesting user's own review comments
 */
export const signalsReportPrReviewCommentUpdateBodyBodyMax = 65536

export const SignalsReportPrReviewCommentUpdateBody = /* @__PURE__ */ zod
    .object({
        body: zod
            .string()
            .max(signalsReportPrReviewCommentUpdateBodyBodyMax)
            .optional()
            .describe('New comment body (GitHub-flavored markdown).'),
    })
    .describe("Request body for editing a review comment's markdown body.")

/**
 * @summary React to a review comment as the requesting user
 */
export const SignalsReportPrReviewCommentReactionsCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod
            .enum(['+1', '-1', 'laugh', 'hooray', 'confused', 'heart', 'rocket', 'eyes'])
            .describe(
                '\* `+1` - +1\n\* `-1` - -1\n\* `laugh` - laugh\n\* `hooray` - hooray\n\* `confused` - confused\n\* `heart` - heart\n\* `rocket` - rocket\n\* `eyes` - eyes'
            )
            .describe(
                "Reaction to add: one of '+1', '-1', 'laugh', 'hooray', 'confused', 'heart', 'rocket', 'eyes'.\n\n\* `+1` - +1\n\* `-1` - -1\n\* `laugh` - laugh\n\* `hooray` - hooray\n\* `confused` - confused\n\* `heart` - heart\n\* `rocket` - rocket\n\* `eyes` - eyes"
            ),
    })
    .describe('Request body for adding an emoji reaction to a review comment.')

/**
 * Refund the flat charge for this report's implementation PR and archive the report. Refunds auto-approve: the charge is either excluded from usage before it is ever reported to billing (refund on the same UTC day as the PR run) or returned as a Stripe customer-balance credit on the next invoice. A refunded PR does not count toward the free monthly PR allowance. One refund per report, ever — repeat calls return the existing refund with already_refunded=true. The report is archived as part of the refund (a resolved report stays resolved) and can't be restored afterwards.
 * @summary Refund a report's implementation PR
 */
export const signalsReportsRefundCreateBodyNoteMax = 4000

export const SignalsReportsRefundCreateBody = /* @__PURE__ */ zod.object({
    reason: zod
        .enum(['pr_incorrect', 'pr_not_useful', 'duplicate', 'other'])
        .describe(
            '\* `pr_incorrect` - PR incorrect\n\* `pr_not_useful` - PR not useful\n\* `duplicate` - Duplicate\n\* `other` - Other'
        )
        .describe(
            "Why this PR is being refunded. One of: pr_incorrect (the PR doesn't address what the report promised), pr_not_useful (technically fine but not worth paying for), duplicate (covers work already charged elsewhere), other. Required — refund reviews key on it.\n\n\* `pr_incorrect` - PR incorrect\n\* `pr_not_useful` - PR not useful\n\* `duplicate` - Duplicate\n\* `other` - Other"
        ),
    note: zod
        .string()
        .max(signalsReportsRefundCreateBodyNoteMax)
        .optional()
        .describe(
            "Optional free-form context for the refund; stored on the refund and echoed in the report's dismissal artefact. Capped at 4000 characters."
        ),
})

/**
 * Transition a report to a new state. The model validates allowed transitions.
 *
 * The request body is validated by SignalReportStateRequestSerializer — only the
 * fields it declares (state, dismissal_reason, dismissal_note, snooze_for) are read,
 * and only snooze_for is ever forwarded to transition_to. Any other key is ignored,
 * so internal transition_to kwargs (reset_weight, error, ...) can't be injected.
 *
 * Body: {
 *     "state": "suppressed" | "potential" | "resolved",
 *     # Optional dismissal feedback (honored when state == "suppressed", "potential", or "resolved"):
 *     "dismissal_reason": "<canonical reason code, see SIGNAL_REPORT_DISMISSAL_REASON_CHOICES>",
 *     "dismissal_note": "free-form text",
 *     # Optional, only honored for state == "potential":
 *     "snooze_for": <number of additional signals before re-promotion>,
 * }
 */
export const signalsReportsStateCreateBodyDismissalNoteMax = 4000

export const signalsReportsStateCreateBodySnoozeForMax = 100000

export const SignalsReportsStateCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .enum(['suppressed', 'potential', 'resolved'])
        .describe('\* `suppressed` - suppressed\n\* `potential` - potential\n\* `resolved` - resolved')
        .describe(
            "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, 'potential' to snooze\/reopen it for later review, or 'resolved' when the work this report asked for has been done. Resolving is only allowed from a researched status (ready or pending_input) or a suppressed report; other statuses return 409 (skipped in bulk).\n\n\* `suppressed` - suppressed\n\* `potential` - potential\n\* `resolved` - resolved"
        ),
    dismissal_reason: zod
        .enum([
            'already_fixed',
            'report_unclear',
            'analysis_wrong',
            'wontfix_intentional',
            'wontfix_irrelevant',
            'other',
        ])
        .describe(
            "\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
        )
        .optional()
        .describe(
            "Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. When the work this report asked for is done, the honest transition is state='resolved' (the reason\/note records why). Reserve 'already_fixed' with state='potential' (snooze\/restore) for \"fixed by something else \/ might recur\" cases, so the report reappears if the issue comes back. Use 'other' together with a dismissal_note for anything that doesn't fit a code.\n\n\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
        ),
    dismissal_note: zod
        .string()
        .max(signalsReportsStateCreateBodyDismissalNoteMax)
        .optional()
        .describe('Optional free-form note explaining the dismissal. Capped at 4000 characters.'),
    snooze_for: zod
        .number()
        .min(1)
        .max(signalsReportsStateCreateBodySnoozeForMax)
        .optional()
        .describe(
            "Optional, only honored when state is 'potential'. Number of additional signals the report must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. Omit to let the report re-enter the pipeline on the next matching signal."
        ),
})

/**
 * Append an artefact to a report (see artefact_type for the writable types). Everything is append-only: log entries (code reference, commit, task run, note) accumulate, while status types (safety / actionability / priority judgments, repo selection, suggested reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status. Content is validated against the type's schema.
 * @summary Append an artefact to a report
 */
export const SignalsReportArtefactsCreateBody = /* @__PURE__ */ zod
    .object({
        artefact_type: zod
            .string()
            .describe(
                "The artefact type. One of: actionability_judgment, code_reference, commit, dismissal, note, priority_judgment, related_to, repo_selection, safety_judgment, signal_finding, suggested_reviewers, task_run. Log types accumulate; status types (safety_judgment, actionability_judgment, priority_judgment, repo_selection, suggested_reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status."
            ),
        content: zod
            .unknown()
            .describe(
                'The artefact payload as a JSON object or array; shape depends on artefact_type and is validated against its schema.'
            ),
    })
    .describe(
        "Body for appending an artefact to a report.\n\nEverything is append-only: log artefacts accumulate, status artefacts supersede the previous\nversion (latest-wins). The `content` shape depends on `artefact_type` and is validated\nagainst the type's schema (see `products\/signals\/backend\/artefact_schemas.py`)."
    )

/**
 * Replace the content of an existing artefact, addressed by id. The new content is validated against the artefact's type schema. Editing the latest row of a status type changes the report's canonical status (latest-wins); to re-assess while keeping history, append a new artefact instead. Attribution is creation-time only — edits don't reassign it.
 * @summary Replace an artefact's content
 */
export const SignalsReportArtefactsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod
            .unknown()
            .optional()
            .describe("The new artefact payload as a JSON object or array, matching the artefact type's schema."),
    })
    .describe(
        "Body for replacing the content of an existing artefact (addressed by id).\n\nPer-type schema validation happens in the view, which knows the artefact's type."
    )

/**
 * Transition many reports to a new state in one call.
 *
 * Each id is processed independently: a report whose transition isn't allowed from its
 * current status is reported as `skipped` (a 409 on the single-report endpoint) and the
 * rest still go through. Returns one result per requested id (in request order, after
 * de-duplication) plus per-outcome counts. The whole call is 200 even on partial failure —
 * inspect `results` / the counts to see what happened.
 */
export const signalsReportsBulkStateCreateBodyDismissalNoteMax = 4000

export const signalsReportsBulkStateCreateBodySnoozeForMax = 100000

export const signalsReportsBulkStateCreateBodyIdsMax = 100

export const SignalsReportsBulkStateCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .enum(['suppressed', 'potential', 'resolved'])
        .describe('\* `suppressed` - suppressed\n\* `potential` - potential\n\* `resolved` - resolved')
        .describe(
            "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, 'potential' to snooze\/reopen it for later review, or 'resolved' when the work this report asked for has been done. Resolving is only allowed from a researched status (ready or pending_input) or a suppressed report; other statuses return 409 (skipped in bulk).\n\n\* `suppressed` - suppressed\n\* `potential` - potential\n\* `resolved` - resolved"
        ),
    dismissal_reason: zod
        .enum([
            'already_fixed',
            'report_unclear',
            'analysis_wrong',
            'wontfix_intentional',
            'wontfix_irrelevant',
            'other',
        ])
        .describe(
            "\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
        )
        .optional()
        .describe(
            "Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. When the work this report asked for is done, the honest transition is state='resolved' (the reason\/note records why). Reserve 'already_fixed' with state='potential' (snooze\/restore) for \"fixed by something else \/ might recur\" cases, so the report reappears if the issue comes back. Use 'other' together with a dismissal_note for anything that doesn't fit a code.\n\n\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
        ),
    dismissal_note: zod
        .string()
        .max(signalsReportsBulkStateCreateBodyDismissalNoteMax)
        .optional()
        .describe('Optional free-form note explaining the dismissal. Capped at 4000 characters.'),
    snooze_for: zod
        .number()
        .min(1)
        .max(signalsReportsBulkStateCreateBodySnoozeForMax)
        .optional()
        .describe(
            "Optional, only honored when state is 'potential'. Number of additional signals the report must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. Omit to let the report re-enter the pipeline on the next matching signal."
        ),
    ids: zod
        .array(zod.uuid())
        .max(signalsReportsBulkStateCreateBodyIdsMax)
        .describe(
            'Report ids to transition to `state` in one call (1–100). Duplicates are de-duplicated; each id is processed independently so one disallowed transition does not block the rest. `dismissal_reason`, `dismissal_note` and `snooze_for` apply to every id.'
        ),
})

/**
 * Create a `signals-scout-*` skill and its runnable config atomically. The skill always receives the report-channel tools. The optional config controls schedule, enablement, dry-run posture, network access, and typed destinations such as Slack. Repeating the same definition is safe and applies any supplied config fields; reusing its name for a different definition returns 409.
 * @summary Create a scout
 */
export const signalsScoutCreateBodyNameMax = 64

export const signalsScoutCreateBodyDescriptionMax = 4096

export const signalsScoutCreateBodyFilesItemPathMax = 500

export const signalsScoutCreateBodyFilesItemContentTypeDefault = `text/plain`
export const signalsScoutCreateBodyFilesItemContentTypeMax = 100

export const signalsScoutCreateBodyConfigOneRunIntervalMinutesMin = 30
export const signalsScoutCreateBodyConfigOneRunIntervalMinutesMax = 43200

export const signalsScoutCreateBodyConfigOneOutputDestinationsOneSlackOneChannelMax = 255

export const signalsScoutCreateBodyConfigOneOutputDestinationsOneSlackOneThreadReportsDefault = false
export const signalsScoutCreateBodyConfigOneRunCronScheduleMax = 100

export const signalsScoutCreateBodyConfigOneModelMax = 200

export const signalsScoutCreateBodyConfigOneTagsMax = 10

export const signalsScoutCreateBodyConfigOneMcpGatewayServerIdsMax = 100

export const SignalsScoutCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(signalsScoutCreateBodyNameMax)
            .describe(
                'Unique scout name. Must start with `signals-scout-` and contain only lowercase letters, numbers, and hyphens.'
            ),
        description: zod
            .string()
            .max(signalsScoutCreateBodyDescriptionMax)
            .describe('Short description of the signal or behavior this scout investigates.'),
        body: zod
            .string()
            .describe(
                'Complete markdown prompt executed on every scout run. Include any project-specific signal names, thresholds, investigation steps, and report criteria here.'
            ),
        files: zod
            .array(
                zod.object({
                    path: zod
                        .string()
                        .max(signalsScoutCreateBodyFilesItemPathMax)
                        .describe(
                            "File path relative to skill root, e.g. 'scripts\/setup.sh' or 'references\/guide.md'."
                        ),
                    content: zod.string().describe('Text content of the file.'),
                    content_type: zod
                        .string()
                        .max(signalsScoutCreateBodyFilesItemContentTypeMax)
                        .default(signalsScoutCreateBodyFilesItemContentTypeDefault)
                        .describe('MIME type of the file content.'),
                })
            )
            .optional()
            .describe('Optional reference files bundled with the scout prompt.'),
        config: zod
            .object({
                enabled: zod
                    .boolean()
                    .optional()
                    .describe('Whether this scout runs on its schedule. Defaults to true.'),
                emit: zod
                    .boolean()
                    .optional()
                    .describe(
                        'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. Defaults to true.'
                    ),
                run_interval_minutes: zod
                    .number()
                    .min(signalsScoutCreateBodyConfigOneRunIntervalMinutesMin)
                    .max(signalsScoutCreateBodyConfigOneRunIntervalMinutesMax)
                    .optional()
                    .describe('Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).'),
                output_destinations: zod
                    .object({
                        slack: zod
                            .union([
                                zod.object({
                                    integration_id: zod
                                        .number()
                                        .min(1)
                                        .describe(
                                            "ID of the Slack integration whose bot posts this scout's findings and reports."
                                        ),
                                    channel: zod
                                        .string()
                                        .max(signalsScoutCreateBodyConfigOneOutputDestinationsOneSlackOneChannelMax)
                                        .nullish()
                                        .describe(
                                            "Slack channel target in the channel picker's `channel_id|#channel-name` format. Null while choosing a channel; no messages are sent until it is set."
                                        ),
                                    thread_reports: zod
                                        .boolean()
                                        .default(
                                            signalsScoutCreateBodyConfigOneOutputDestinationsOneSlackOneThreadReportsDefault
                                        )
                                        .describe(
                                            "When true, post a report as a thread: a short lead in the channel and the rest split by the report's Markdown headings into replies. Keeps a long summary from being clipped at Slack's section limit. Off by default, and it does not change how findings post."
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                'Slack destination for each emitted scout finding or report. Null or omitted disables Slack delivery.'
                            ),
                        webhook: zod
                            .union([
                                zod.object({
                                    hog_function_id: zod
                                        .string()
                                        .describe(
                                            "Id of the CDP destination delivering this scout's reports. Set by the product that provisioned it, so it can find that destination again to update or remove it."
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                "The CDP destination another product provisioned for this scout's reports. Null or omitted means no webhook. Unlike Slack, Signals does not deliver this itself: the reference lives here so the owning product can manage the destination's lifecycle."
                            ),
                    })
                    .optional()
                    .describe('Destinations that receive each finding or report this scout emits. Empty by default.'),
                network_access: zod
                    .enum(['trusted', 'full'])
                    .describe('\* `trusted` - Trusted domains only\n\* `full` - Full')
                    .optional()
                    .describe(
                        "What the scout's sandbox can reach over the network while it runs. Defaults to `trusted`, the platform's trusted-domain allowlist (PostHog, GitHub, common package registries). Set `full` to let this scout reach any site, for skills that read external sources such as documentation or papers.\n\n\* `trusted` - Trusted domains only\n\* `full` - Full"
                    ),
                auto_pause_exempt: zod
                    .boolean()
                    .optional()
                    .describe(
                        'Exempt this scout from the inactivity pause, which otherwise switches off a scout that goes a fortnight without surfacing anything anyone engages with. Set it on watchdog scouts whose value is staying quiet. Defaults to false.'
                    ),
                run_cron_schedule: zod
                    .string()
                    .max(signalsScoutCreateBodyConfigOneRunCronScheduleMax)
                    .nullish()
                    .describe(
                        "Optional five-field cron expression, e.g. '30 9 \* \* \*' (daily at 09:30), '0 9,17 \* \* \*' (twice daily), or '0 9 \* \* 1-5' (weekday mornings). Evaluated in the project timezone. Takes precedence over `run_interval_minutes`; occurrences must be at least 30 minutes apart."
                    ),
                model: zod
                    .string()
                    .max(signalsScoutCreateBodyConfigOneModelMax)
                    .nullish()
                    .describe(
                        "Optional model id this scout's runs are pinned to, e.g. `claude-opus-4-5`. Must be one of the platform's agent models; an invalid id is rejected with the available ones listed. Null keeps the default model, chosen by the platform. Early access: the pin can only be set on projects enrolled in the scout model preview, and only takes effect there. Set null to clear it."
                    ),
                tags: zod
                    .array(zod.string())
                    .max(signalsScoutCreateBodyConfigOneTagsMax)
                    .optional()
                    .describe(
                        'Free-form labels for grouping the fleet, e.g. `[\"revenue\", \"on-call\"]`. Normalized to lowercase kebab-case (`On Call` and `on_call` both become `on-call`), deduped, and stored sorted; at most 10 tags, each at most 50 characters once normalized. Pass the full desired set — a write replaces the existing tags rather than merging into them. Filter the config list with the `tags` query parameter.'
                    ),
                structured_output_schema: zod
                    .record(zod.string(), zod.unknown())
                    .nullish()
                    .describe(
                        'Optional JSON Schema (draft 2020-12) describing ONE structured record this scout produces via `scout-record-output` — e.g. a per-report quality judgment (`{\"type\": \"object\", \"properties\": {\"verdict\": {\"enum\": [\"good\", \"bad\", \"unsure\"]}, \"reason\": {\"type\": \"string\"}}, \"required\": [\"verdict\", \"reason\"]}`). The root must be `\"type\": \"object\"`. Setting a schema turns the structured-output channel on: the run prompt renders the schema and every submitted record is validated against it and recorded in the project as a `$scout_structured_output` event, queryable like any event. The channel also requires emit — a dry-run scout has nowhere to record to. Cardinality is the scout\'s call (one record per run, one per judged entity, ...). Null = channel off. Setting a schema requires skill-authoring authorization (the `llm_skill:write` scope and skill editor access) since the scout reads it verbatim in its prompt; clearing it needs only the config write. Records validate against the schema in force when the run was dispatched.'
                    ),
                mcp_gateway_server_ids: zod
                    .array(zod.uuid())
                    .max(signalsScoutCreateBodyConfigOneMcpGatewayServerIdsMax)
                    .optional()
                    .describe(
                        "MCP gateway servers (by id) this scout's runs may use, chosen from the connections members shared to the whole team. Selection is per scout: an empty list gives the scout no MCP servers. Applies from the scout's next run."
                    ),
            })
            .describe('Schedule, enablement, and delivery options accepted while creating a scout.')
            .optional()
            .describe(
                'Optional schedule, enablement, dry-run posture, and delivery settings. Defaults to an enabled, emitting scout on the daily interval with no external destination.'
            ),
    })
    .describe('Create a runnable custom scout and its config in one atomic request.')

/**
 * Create and run a cloud task for one of the fixed scout chat templates (suggest a scout, fleet overview, recent signals). The prompt is server-owned; the response carries the task id to navigate to.
 * @summary Start a scout chat task
 */
export const SignalsScoutChatTasksCreateBody = /* @__PURE__ */ zod.object({
    chat_type: zod
        .enum(['author_scout', 'fleet_overview', 'recent_signals'])
        .describe(
            '\* `author_scout` - author_scout\n\* `fleet_overview` - fleet_overview\n\* `recent_signals` - recent_signals'
        )
        .describe(
            'Which scout chat to start: `author_scout` (guided scout authoring), `fleet_overview` (health of the scout fleet), or `recent_signals` (walk through recently emitted signals). The prompt template is owned server-side.\n\n\* `author_scout` - author_scout\n\* `fleet_overview` - fleet_overview\n\* `recent_signals` - recent_signals'
        ),
})

/**
 * Register the config for a `signals-scout-*` skill immediately, without waiting for the coordinator to auto-register it. The same call can optionally set `run_interval_minutes`, a cron `run_cron_schedule`, `enabled`, `emit`, `network_access`, and output destinations. The skill must already exist on this project. Upsert: if a config already exists for the skill, the provided fields are applied to it.
 * @summary Create a scout config
 */
export const signalsScoutConfigCreateBodyRunIntervalMinutesMin = 30
export const signalsScoutConfigCreateBodyRunIntervalMinutesMax = 43200

export const signalsScoutConfigCreateBodyOutputDestinationsOneSlackOneChannelMax = 255

export const signalsScoutConfigCreateBodyOutputDestinationsOneSlackOneThreadReportsDefault = false
export const signalsScoutConfigCreateBodyRunCronScheduleMax = 100

export const signalsScoutConfigCreateBodyModelMax = 200

export const signalsScoutConfigCreateBodyTagsMax = 10

export const signalsScoutConfigCreateBodyMcpGatewayServerIdsMax = 100

export const signalsScoutConfigCreateBodySkillNameMax = 200

export const SignalsScoutConfigCreateBody = /* @__PURE__ */ zod
    .object({
        enabled: zod.boolean().optional().describe('Whether this scout runs on its schedule. Defaults to true.'),
        emit: zod
            .boolean()
            .optional()
            .describe(
                'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. Defaults to true.'
            ),
        run_interval_minutes: zod
            .number()
            .min(signalsScoutConfigCreateBodyRunIntervalMinutesMin)
            .max(signalsScoutConfigCreateBodyRunIntervalMinutesMax)
            .optional()
            .describe('Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).'),
        output_destinations: zod
            .object({
                slack: zod
                    .union([
                        zod.object({
                            integration_id: zod
                                .number()
                                .min(1)
                                .describe(
                                    "ID of the Slack integration whose bot posts this scout's findings and reports."
                                ),
                            channel: zod
                                .string()
                                .max(signalsScoutConfigCreateBodyOutputDestinationsOneSlackOneChannelMax)
                                .nullish()
                                .describe(
                                    "Slack channel target in the channel picker's `channel_id|#channel-name` format. Null while choosing a channel; no messages are sent until it is set."
                                ),
                            thread_reports: zod
                                .boolean()
                                .default(signalsScoutConfigCreateBodyOutputDestinationsOneSlackOneThreadReportsDefault)
                                .describe(
                                    "When true, post a report as a thread: a short lead in the channel and the rest split by the report's Markdown headings into replies. Keeps a long summary from being clipped at Slack's section limit. Off by default, and it does not change how findings post."
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'Slack destination for each emitted scout finding or report. Null or omitted disables Slack delivery.'
                    ),
                webhook: zod
                    .union([
                        zod.object({
                            hog_function_id: zod
                                .string()
                                .describe(
                                    "Id of the CDP destination delivering this scout's reports. Set by the product that provisioned it, so it can find that destination again to update or remove it."
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        "The CDP destination another product provisioned for this scout's reports. Null or omitted means no webhook. Unlike Slack, Signals does not deliver this itself: the reference lives here so the owning product can manage the destination's lifecycle."
                    ),
            })
            .optional()
            .describe('Destinations that receive each finding or report this scout emits. Empty by default.'),
        network_access: zod
            .enum(['trusted', 'full'])
            .describe('\* `trusted` - Trusted domains only\n\* `full` - Full')
            .optional()
            .describe(
                "What the scout's sandbox can reach over the network while it runs. Defaults to `trusted`, the platform's trusted-domain allowlist (PostHog, GitHub, common package registries). Set `full` to let this scout reach any site, for skills that read external sources such as documentation or papers.\n\n\* `trusted` - Trusted domains only\n\* `full` - Full"
            ),
        auto_pause_exempt: zod
            .boolean()
            .optional()
            .describe(
                'Exempt this scout from the inactivity pause, which otherwise switches off a scout that goes a fortnight without surfacing anything anyone engages with. Set it on watchdog scouts whose value is staying quiet. Defaults to false.'
            ),
        run_cron_schedule: zod
            .string()
            .max(signalsScoutConfigCreateBodyRunCronScheduleMax)
            .nullish()
            .describe(
                "Optional five-field cron expression, e.g. '30 9 \* \* \*' (daily at 09:30), '0 9,17 \* \* \*' (twice daily), or '0 9 \* \* 1-5' (weekday mornings). Evaluated in the project timezone. Takes precedence over `run_interval_minutes`; occurrences must be at least 30 minutes apart."
            ),
        model: zod
            .string()
            .max(signalsScoutConfigCreateBodyModelMax)
            .nullish()
            .describe(
                "Optional model id this scout's runs are pinned to, e.g. `claude-opus-4-5`. Must be one of the platform's agent models; an invalid id is rejected with the available ones listed. Null keeps the default model, chosen by the platform. Early access: the pin can only be set on projects enrolled in the scout model preview, and only takes effect there. Set null to clear it."
            ),
        tags: zod
            .array(zod.string())
            .max(signalsScoutConfigCreateBodyTagsMax)
            .optional()
            .describe(
                'Free-form labels for grouping the fleet, e.g. `[\"revenue\", \"on-call\"]`. Normalized to lowercase kebab-case (`On Call` and `on_call` both become `on-call`), deduped, and stored sorted; at most 10 tags, each at most 50 characters once normalized. Pass the full desired set — a write replaces the existing tags rather than merging into them. Filter the config list with the `tags` query parameter.'
            ),
        structured_output_schema: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'Optional JSON Schema (draft 2020-12) describing ONE structured record this scout produces via `scout-record-output` — e.g. a per-report quality judgment (`{\"type\": \"object\", \"properties\": {\"verdict\": {\"enum\": [\"good\", \"bad\", \"unsure\"]}, \"reason\": {\"type\": \"string\"}}, \"required\": [\"verdict\", \"reason\"]}`). The root must be `\"type\": \"object\"`. Setting a schema turns the structured-output channel on: the run prompt renders the schema and every submitted record is validated against it and recorded in the project as a `$scout_structured_output` event, queryable like any event. The channel also requires emit — a dry-run scout has nowhere to record to. Cardinality is the scout\'s call (one record per run, one per judged entity, ...). Null = channel off. Setting a schema requires skill-authoring authorization (the `llm_skill:write` scope and skill editor access) since the scout reads it verbatim in its prompt; clearing it needs only the config write. Records validate against the schema in force when the run was dispatched.'
            ),
        mcp_gateway_server_ids: zod
            .array(zod.uuid())
            .max(signalsScoutConfigCreateBodyMcpGatewayServerIdsMax)
            .optional()
            .describe(
                "MCP gateway servers (by id) this scout's runs may use, chosen from the connections members shared to the whole team. Selection is per scout: an empty list gives the scout no MCP servers. Applies from the scout's next run."
            ),
        skill_name: zod
            .string()
            .max(signalsScoutConfigCreateBodySkillNameMax)
            .describe(
                'The `signals-scout-\*` skill to register a config for. The skill must already exist on this project — author it via the skills store first.'
            ),
    })
    .describe(
        'Request body for registering a scout config without waiting for the coordinator tick.\n\nUpsert keyed on `skill_name`: if the coordinator (or a concurrent caller) already\nregistered the row, the provided tunables are applied to it instead.'
    )

/**
 * Tune one scout: change its schedule (rolling `run_interval_minutes`, or a cron `run_cron_schedule` that takes precedence when set), `enabled`, `emit` (dry-run) posture, `network_access` (trusted-domain allowlist vs full access for the scout's sandbox), or output destinations. `skill_name` is fixed. Enabling records `enabled_by` and is activity-logged since it drives spend.
 * @summary Update a scout config
 */
export const signalsScoutConfigUpdateBodyRunIntervalMinutesMin = 30
export const signalsScoutConfigUpdateBodyRunIntervalMinutesMax = 43200

export const signalsScoutConfigUpdateBodyRunCronScheduleMax = 100

export const signalsScoutConfigUpdateBodyOutputDestinationsOneSlackOneChannelMax = 255

export const signalsScoutConfigUpdateBodyOutputDestinationsOneSlackOneThreadReportsDefault = false
export const signalsScoutConfigUpdateBodyModelMax = 200

export const signalsScoutConfigUpdateBodyTagsMax = 10

export const signalsScoutConfigUpdateBodyMcpGatewayServerIdsMax = 100

export const SignalsScoutConfigUpdateBody = /* @__PURE__ */ zod
    .object({
        enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this scout runs on its schedule. Disabled scouts are skipped by the coordinator. Turning this off records a user pause (`status` becomes `paused_by_user`, which the system never overrides); turning it on resumes the scout from any pause. Only a change of value is a lifecycle action: re-sending the current value leaves the existing status and its ownership untouched.'
            ),
        emit: zod
            .boolean()
            .optional()
            .describe(
                'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing.'
            ),
        run_interval_minutes: zod
            .number()
            .min(signalsScoutConfigUpdateBodyRunIntervalMinutesMin)
            .max(signalsScoutConfigUpdateBodyRunIntervalMinutesMax)
            .optional()
            .describe('Minutes between runs (30–43200). Use 1440 for a daily schedule.'),
        run_cron_schedule: zod
            .string()
            .max(signalsScoutConfigUpdateBodyRunCronScheduleMax)
            .nullish()
            .describe(
                "Optional five-field cron expression, e.g. '30 9 \* \* \*' (daily at 09:30), '0 9,17 \* \* \*' (twice daily), or '0 9 \* \* 1-5' (weekday mornings). Evaluated in the project timezone. Takes precedence over `run_interval_minutes`; occurrences must be at least 30 minutes apart. Set null to return to the rolling interval schedule."
            ),
        output_destinations: zod
            .object({
                slack: zod
                    .union([
                        zod.object({
                            integration_id: zod
                                .number()
                                .min(1)
                                .describe(
                                    "ID of the Slack integration whose bot posts this scout's findings and reports."
                                ),
                            channel: zod
                                .string()
                                .max(signalsScoutConfigUpdateBodyOutputDestinationsOneSlackOneChannelMax)
                                .nullish()
                                .describe(
                                    "Slack channel target in the channel picker's `channel_id|#channel-name` format. Null while choosing a channel; no messages are sent until it is set."
                                ),
                            thread_reports: zod
                                .boolean()
                                .default(signalsScoutConfigUpdateBodyOutputDestinationsOneSlackOneThreadReportsDefault)
                                .describe(
                                    "When true, post a report as a thread: a short lead in the channel and the rest split by the report's Markdown headings into replies. Keeps a long summary from being clipped at Slack's section limit. Off by default, and it does not change how findings post."
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'Slack destination for each emitted scout finding or report. Null or omitted disables Slack delivery.'
                    ),
                webhook: zod
                    .union([
                        zod.object({
                            hog_function_id: zod
                                .string()
                                .describe(
                                    "Id of the CDP destination delivering this scout's reports. Set by the product that provisioned it, so it can find that destination again to update or remove it."
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        "The CDP destination another product provisioned for this scout's reports. Null or omitted means no webhook. Unlike Slack, Signals does not deliver this itself: the reference lives here so the owning product can manage the destination's lifecycle."
                    ),
            })
            .optional()
            .describe(
                'Destinations that receive each finding or report this scout emits. Pass an empty object to disable delivery.'
            ),
        structured_output_schema: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'Optional JSON Schema (draft 2020-12) describing ONE structured record this scout produces via `scout-record-output` — e.g. a per-report quality judgment (`{\"type\": \"object\", \"properties\": {\"verdict\": {\"enum\": [\"good\", \"bad\", \"unsure\"]}, \"reason\": {\"type\": \"string\"}}, \"required\": [\"verdict\", \"reason\"]}`). The root must be `\"type\": \"object\"`. Setting a schema turns the structured-output channel on: the run prompt renders the schema and every submitted record is validated against it and recorded in the project as a `$scout_structured_output` event, queryable like any event. The channel also requires emit — a dry-run scout has nowhere to record to. Cardinality is the scout\'s call (one record per run, one per judged entity, ...). Null = channel off. Setting a schema requires skill-authoring authorization (the `llm_skill:write` scope and skill editor access) since the scout reads it verbatim in its prompt; clearing it needs only the config write. Records validate against the schema in force when the run was dispatched.'
            ),
        network_access: zod
            .enum(['trusted', 'full'])
            .describe('\* `trusted` - Trusted domains only\n\* `full` - Full')
            .optional()
            .describe(
                "What the scout's sandbox can reach over the network while it runs. `trusted` (the default) restricts runs to the platform's trusted-domain allowlist (PostHog, GitHub, common package registries). Set `full` to let this scout reach any site, for skills that read external sources such as documentation or papers. Applies from the scout's next run.\n\n\* `trusted` - Trusted domains only\n\* `full` - Full"
            ),
        model: zod
            .string()
            .max(signalsScoutConfigUpdateBodyModelMax)
            .nullish()
            .describe(
                "Optional model id this scout's runs are pinned to, e.g. `claude-opus-4-5`. Must be one of the platform's agent models; an invalid id is rejected with the available ones listed. Null keeps the default model, chosen by the platform. Early access: the pin can only be set on projects enrolled in the scout model preview, and only takes effect there. Set null to clear it."
            ),
        auto_pause_exempt: zod
            .boolean()
            .optional()
            .describe(
                'Exempt this scout from the inactivity sweep, meaning both the `ignored` pause and the `no_output` quiet warning. Set it on watchdog scouts whose value is staying quiet.'
            ),
        tags: zod
            .array(zod.string())
            .max(signalsScoutConfigUpdateBodyTagsMax)
            .optional()
            .describe(
                'Free-form labels for grouping the fleet, e.g. `[\"revenue\", \"on-call\"]`. Normalized to lowercase kebab-case (`On Call` and `on_call` both become `on-call`), deduped, and stored sorted; at most 10 tags, each at most 50 characters once normalized. Pass the full desired set — a write replaces the existing tags rather than merging into them. Filter the config list with the `tags` query parameter.'
            ),
        mcp_gateway_server_ids: zod
            .array(zod.uuid())
            .max(signalsScoutConfigUpdateBodyMcpGatewayServerIdsMax)
            .optional()
            .describe(
                "MCP gateway servers (by id) this scout's runs may use, chosen from the connections members shared to the whole team. Selection is per scout: an empty list gives the scout no MCP servers. Applies from the scout's next run."
            ),
    })
    .describe('Editable schedule, enablement, and emit posture for one scout config.')

/**
 * Leave a steering note the scout fleet reads on its next runs. Address it to one scout via `skill_name` (`signals-scout-*`), or omit it for a general note every scout sees. Each call creates a new note (no upsert); delete retires one. Attributed to the authenticated user.
 * @summary Leave a note for the scouts
 */
export const signalsScoutNotesCreateBodyContentMax = 10000

export const signalsScoutNotesCreateBodySkillNameMax = 200

export const SignalsScoutNotesCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod
            .string()
            .max(signalsScoutNotesCreateBodyContentMax)
            .describe(
                "The note's prose — feedback, a pointer, or a nudge for the scout(s) to weigh on their next runs (e.g. 'we shipped a new checkout on Tuesday, watch conversion closely', 'stop flagging the staging traffic spike'). Write it in Markdown; scouts read it verbatim."
            ),
        skill_name: zod
            .string()
            .max(signalsScoutNotesCreateBodySkillNameMax)
            .optional()
            .describe(
                'Address the note to one scout by its skill name (`signals-scout-\*`, exact match against an existing scout skill on the project — check `scout-config-list` for the roster). Omit or leave blank for a general note every scout sees.'
            ),
        expires_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe(
                "Optional ISO-8601 expiry. After this time the note drops out of the default list view, so time-boxed steering ('watch closely this week') retires itself. Omit for a note that stays active until deleted."
            ),
    })
    .describe('Request body for `notes-create`.')

/**
 * Rewrite a report's title/summary, append a note, and/or set its suggested reviewers. Can target ANY of the project's inbox reports, not just scout-authored ones — so the edit is attributed to this scout. Setting reviewers is how you rescue a report that surfaced routed to no one: it replaces the reviewer list and re-runs autostart, so a report missing a qualifying reviewer can open a draft PR. Title/summary edits are best-effort: the pipeline may later re-research them.
 * @summary Edit an existing report for a run
 */
export const signalsScoutEditReportBodyTitleMax = 300

export const signalsScoutEditReportBodySuggestedReviewersItemGithubLoginMax = 200

export const signalsScoutEditReportBodySuggestedReviewersItemReasonMax = 500

export const signalsScoutEditReportBodySuggestedReviewersMax = 10

export const signalsScoutEditReportBodyChartsItemChartIdMax = 100

export const signalsScoutEditReportBodyChartsItemTitleMax = 200

export const signalsScoutEditReportBodyChartsItemCaptionMax = 500

export const signalsScoutEditReportBodyChartsMax = 20

export const signalsScoutEditReportBodySuggestedPromptsItemMax = 200

export const signalsScoutEditReportBodySuggestedPromptsMax = 3

export const SignalsScoutEditReportBody = /* @__PURE__ */ zod
    .object({
        report_id: zod.string().describe('Id of the report to edit (must belong to this project).'),
        title: zod
            .string()
            .max(signalsScoutEditReportBodyTitleMax)
            .nullish()
            .describe(
                'Optional new title. Conventional-commit style (`type(scope): description`) renders with type\/scope styling. The pipeline may later re-research and overwrite it.'
            ),
        summary: zod
            .string()
            .nullish()
            .describe(
                'Optional new summary. Markdown is supported (headings, lists, code, links; images are not rendered); lead with one plain declarative sentence — it becomes the inbox card headline. The pipeline may later re-research and overwrite it.'
            ),
        append_note: zod
            .string()
            .nullish()
            .describe("Optional free-form note to append to the report's work log (attributed to this scout)."),
        suggested_reviewers: zod
            .array(
                zod
                    .object({
                        github_login: zod
                            .string()
                            .max(signalsScoutEditReportBodySuggestedReviewersItemGithubLoginMax)
                            .optional()
                            .describe(
                                'GitHub login (case-insensitive, stored lowercased) — e.g. `octocat`, no `@`, no display name. Resolve one via `scout-members-list` (each member row carries a resolved `github_login`) or git history when you only have a name.'
                            ),
                        user_uuid: zod
                            .uuid()
                            .optional()
                            .describe(
                                "PostHog user UUID (e.g. from `scout-members-list`, or an entity's `created_by`). Resolved server-side to the member's linked GitHub login — use this when you know the PostHog user but not their GitHub handle. Must be a concrete UUID; the `@me` alias is not valid here."
                            ),
                        reason: zod
                            .string()
                            .max(signalsScoutEditReportBodySuggestedReviewersItemReasonMax)
                            .nullish()
                            .describe(
                                "One sentence of evidence for WHY this person: what ties them to the affected surface (e.g. 'authored 4 of the last 10 commits touching products\/tracing\/mcp\/', 'human correction routed the prior tracing report to them'). Persisted on the report so the routing is auditable — always set it when you can name the evidence; 'precedent' alone is weak, prefer code-derived ownership."
                            ),
                    })
                    .describe(
                        "One suggested reviewer — identified by `github_login`, `user_uuid`, or both.\n\nThe server canonicalizes each entry to a lowercased GitHub login: a `user_uuid` is resolved to the\norg member's linked GitHub login (and wins over a supplied `github_login` when both are given). A\n`user_uuid` that isn't an org member of this team with a linked GitHub identity is rejected — so a\nreviewer is never silently dropped."
                    )
            )
            .max(signalsScoutEditReportBodySuggestedReviewersMax)
            .optional()
            .describe(
                'Optional reviewers to set on the report (each a `github_login` and\/or `user_uuid`), replacing any existing list. Use this to route a report that surfaced with no reviewer — it re-runs autostart, so a report that was missing a qualifying reviewer can now open a draft PR. An empty list is a no-op (existing reviewers are left untouched, never cleared).'
            ),
        charts: zod
            .array(
                zod
                    .object({
                        chart_id: zod
                            .string()
                            .max(signalsScoutEditReportBodyChartsItemChartIdMax)
                            .describe(
                                "Stable slug for this chart within the report (lowercase letters, numbers, underscores, hyphens; must start with a letter or number). Reference it from `summary` as a markdown link with a `chart:` target — `[Daily signups](chart:signups-drop)` — to place the chart at that point in the body. A chart you don't reference still renders, below the summary."
                            ),
                        title: zod
                            .string()
                            .max(signalsScoutEditReportBodyChartsItemTitleMax)
                            .describe('Short heading shown above the chart.'),
                        query: zod
                            .unknown()
                            .describe(
                                'The query node to render. `kind` must be `InsightVizNode` (an ad-hoc product analytics chart), `DataVisualizationNode` (a SQL series — a `HogQLQuery` source plus a `display`), or `SavedInsightNode` (an existing insight by `shortId`). Pin the window to absolute dates where the node supports it, so the reader sees the data you wrote about rather than whatever a relative range resolves to when they open the report.'
                            ),
                        caption: zod
                            .string()
                            .max(signalsScoutEditReportBodyChartsItemCaptionMax)
                            .nullish()
                            .describe('Optional one-line note on what to look at in the chart.'),
                        size: zod
                            .union([
                                zod
                                    .enum(['small', 'medium', 'large'])
                                    .describe('\* `small` - small\n\* `medium` - medium\n\* `large` - large'),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                'How much height the chart gets: `small` for a single number or a short series, `medium` for an ordinary graph, `large` when there are rows or a grid to read (retention, paths, a wide breakdown). Leave it out unless the default looks wrong — the inbox sizes a chart from its query, and two charts referenced from the same paragraph sit side by side.\n\n\* `small` - small\n\* `medium` - medium\n\* `large` - large'
                            ),
                    })
                    .describe(
                        'One chart attached to a report — rendered in the inbox and referenceable from the summary.'
                    )
            )
            .max(signalsScoutEditReportBodyChartsMax)
            .nullish()
            .describe(
                "The full set of charts the report should show. Replaces the report's charts rather than adding to them, the way `summary` replaces the summary — so send every chart you want kept. Omit the field (or send null) to leave the report's existing charts untouched, and send an empty list to take them all down."
            ),
        suggested_prompts: zod
            .array(zod.string().max(signalsScoutEditReportBodySuggestedPromptsItemMax))
            .max(signalsScoutEditReportBodySuggestedPromptsMax)
            .nullish()
            .describe(
                "The full set of follow-up questions the report should offer above its `Ask AI` box. Replaces the report's questions rather than adding to them, so send every one you want kept. Omit the field (or send null) to leave them untouched, and send an empty list to take them down, which is what you want once a rewrite has left them answering the old report."
            ),
    })
    .describe(
        "Request body for `edit-report`. Can target ANY of the team's inbox reports, not just scout-authored ones."
    )

/**
 * The second emit channel: author a complete `SignalReport` directly instead of emitting a weak signal. The report passes the safety judge, then surfaces at the status the scout's `actionability` call implies (or is suppressed). Backing `evidence` is written as bound signals so the report behaves like a pipeline report. NOT idempotent — a retry authors a second report; use `reports` to find a prior report and `edit-report` to update it instead.
 * @summary Author a full report for a run
 */
export const signalsScoutEmitReportBodyTitleMax = 300

export const signalsScoutEmitReportBodyEvidenceItemWeightMin = 0

export const signalsScoutEmitReportBodyAlreadyAddressedDefault = false
export const signalsScoutEmitReportBodySuggestedReviewersItemGithubLoginMax = 200

export const signalsScoutEmitReportBodySuggestedReviewersItemReasonMax = 500

export const signalsScoutEmitReportBodySuggestedReviewersMax = 10

export const signalsScoutEmitReportBodyChartsItemChartIdMax = 100

export const signalsScoutEmitReportBodyChartsItemTitleMax = 200

export const signalsScoutEmitReportBodyChartsItemCaptionMax = 500

export const signalsScoutEmitReportBodyChartsMax = 20

export const signalsScoutEmitReportBodySuggestedPromptsItemMax = 200

export const signalsScoutEmitReportBodySuggestedPromptsMax = 3

export const SignalsScoutEmitReportBody = /* @__PURE__ */ zod
    .object({
        title: zod
            .string()
            .max(signalsScoutEmitReportBodyTitleMax)
            .describe(
                'One-line report title the inbox shows. Conventional-commit style (`type(scope): description`, e.g. `fix(insights): missing series color`) renders with type\/scope styling.'
            ),
        summary: zod
            .string()
            .describe(
                'The report body the inbox shows. Markdown is supported (headings, lists, code, links; images are not rendered). Lead with one plain declarative sentence — the inbox card uses your first line verbatim as the headline (~140 chars, emphasis stripped), then renders the full markdown in the detail view.'
            ),
        evidence: zod
            .array(
                zod
                    .object({
                        description: zod
                            .string()
                            .describe(
                                'Prose for this observation. Embedded and rendered to the safety\/research surfaces.'
                            ),
                        source_id: zod
                            .string()
                            .describe(
                                'Stable id for this observation within the report (lets a later edit address it).'
                            ),
                        weight: zod
                            .number()
                            .min(signalsScoutEmitReportBodyEvidenceItemWeightMin)
                            .optional()
                            .describe('Optional per-signal weight (defaults to 1.0). Scouts rarely need to set this.'),
                    })
                    .describe('One observation backing an authored report — becomes a bound signal row on the report.')
            )
            .min(1)
            .describe('The observations backing the report — each becomes a bound signal. At least one.'),
        actionability_explanation: zod
            .string()
            .describe('2-3 sentence evidence-grounded justification for the actionability call below.'),
        actionability: zod
            .enum(['immediately_actionable', 'requires_human_input', 'not_actionable'])
            .describe(
                '\* `immediately_actionable` - immediately_actionable\n\* `requires_human_input` - requires_human_input\n\* `not_actionable` - not_actionable'
            )
            .describe(
                "The scout's actionability call: `immediately_actionable` -> the report surfaces READY; `requires_human_input` -> PENDING_INPUT; `not_actionable` -> suppressed. A safety-judge failure suppresses the report regardless.\n\n\* `immediately_actionable` - immediately_actionable\n\* `requires_human_input` - requires_human_input\n\* `not_actionable` - not_actionable"
            ),
        already_addressed: zod
            .boolean()
            .default(signalsScoutEmitReportBodyAlreadyAddressedDefault)
            .describe(
                'Whether the issue is already being handled — fixed in recent changes, or with a fix in flight (an open PR, a recently active branch, an assigned \/ in-progress issue or agent task). Gates autostart, so a wrong `false` opens a duplicate PR. Tracked separately.'
            ),
        repository: zod
            .string()
            .nullish()
            .describe(
                "Optional repo for autostart (opening a draft PR): `owner\/repo` targets that repo, the `NO_REPO` sentinel opts out (report lands without a PR), and omitting it triggers free-form selection across the team's repos — the slow path on a many-repo team, so pass `owner\/repo` when you know it."
            ),
        priority: zod
            .union([
                zod
                    .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                    .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Optional priority (`P0`-`P4`). Required for autostart; pair with `priority_explanation`.\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
            ),
        priority_explanation: zod
            .string()
            .nullish()
            .describe('2-3 sentence justification for `priority`. Required when `priority` is set.'),
        suggested_reviewers: zod
            .array(
                zod
                    .object({
                        github_login: zod
                            .string()
                            .max(signalsScoutEmitReportBodySuggestedReviewersItemGithubLoginMax)
                            .optional()
                            .describe(
                                'GitHub login (case-insensitive, stored lowercased) — e.g. `octocat`, no `@`, no display name. Resolve one via `scout-members-list` (each member row carries a resolved `github_login`) or git history when you only have a name.'
                            ),
                        user_uuid: zod
                            .uuid()
                            .optional()
                            .describe(
                                "PostHog user UUID (e.g. from `scout-members-list`, or an entity's `created_by`). Resolved server-side to the member's linked GitHub login — use this when you know the PostHog user but not their GitHub handle. Must be a concrete UUID; the `@me` alias is not valid here."
                            ),
                        reason: zod
                            .string()
                            .max(signalsScoutEmitReportBodySuggestedReviewersItemReasonMax)
                            .nullish()
                            .describe(
                                "One sentence of evidence for WHY this person: what ties them to the affected surface (e.g. 'authored 4 of the last 10 commits touching products\/tracing\/mcp\/', 'human correction routed the prior tracing report to them'). Persisted on the report so the routing is auditable — always set it when you can name the evidence; 'precedent' alone is weak, prefer code-derived ownership."
                            ),
                    })
                    .describe(
                        "One suggested reviewer — identified by `github_login`, `user_uuid`, or both.\n\nThe server canonicalizes each entry to a lowercased GitHub login: a `user_uuid` is resolved to the\norg member's linked GitHub login (and wins over a supplied `github_login` when both are given). A\n`user_uuid` that isn't an org member of this team with a linked GitHub identity is rejected — so a\nreviewer is never silently dropped."
                    )
            )
            .max(signalsScoutEmitReportBodySuggestedReviewersMax)
            .optional()
            .describe(
                "Optional reviewers to route the report to (each a `github_login` and\/or `user_uuid`). This is the primary way a report reaches a human — the inbox floats a reviewer's own reports to the top of their inbox even when no PR is involved — so set it whenever you can name a plausible owner. It also gates autostart: a PR opens only if at least one reviewer clears their autonomy threshold."
            ),
        charts: zod
            .array(
                zod
                    .object({
                        chart_id: zod
                            .string()
                            .max(signalsScoutEmitReportBodyChartsItemChartIdMax)
                            .describe(
                                "Stable slug for this chart within the report (lowercase letters, numbers, underscores, hyphens; must start with a letter or number). Reference it from `summary` as a markdown link with a `chart:` target — `[Daily signups](chart:signups-drop)` — to place the chart at that point in the body. A chart you don't reference still renders, below the summary."
                            ),
                        title: zod
                            .string()
                            .max(signalsScoutEmitReportBodyChartsItemTitleMax)
                            .describe('Short heading shown above the chart.'),
                        query: zod
                            .unknown()
                            .describe(
                                'The query node to render. `kind` must be `InsightVizNode` (an ad-hoc product analytics chart), `DataVisualizationNode` (a SQL series — a `HogQLQuery` source plus a `display`), or `SavedInsightNode` (an existing insight by `shortId`). Pin the window to absolute dates where the node supports it, so the reader sees the data you wrote about rather than whatever a relative range resolves to when they open the report.'
                            ),
                        caption: zod
                            .string()
                            .max(signalsScoutEmitReportBodyChartsItemCaptionMax)
                            .nullish()
                            .describe('Optional one-line note on what to look at in the chart.'),
                        size: zod
                            .union([
                                zod
                                    .enum(['small', 'medium', 'large'])
                                    .describe('\* `small` - small\n\* `medium` - medium\n\* `large` - large'),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                'How much height the chart gets: `small` for a single number or a short series, `medium` for an ordinary graph, `large` when there are rows or a grid to read (retention, paths, a wide breakdown). Leave it out unless the default looks wrong — the inbox sizes a chart from its query, and two charts referenced from the same paragraph sit side by side.\n\n\* `small` - small\n\* `medium` - medium\n\* `large` - large'
                            ),
                    })
                    .describe(
                        'One chart attached to a report — rendered in the inbox and referenceable from the summary.'
                    )
            )
            .max(signalsScoutEmitReportBodyChartsMax)
            .optional()
            .describe(
                'Optional charts to attach to the report — the inbox renders them inline, so a metric move is something the reader sees rather than a number they take on trust. Attach one whenever the finding rests on a trend, a spike, or a comparison you already queried.'
            ),
        suggested_prompts: zod
            .array(zod.string().max(signalsScoutEmitReportBodySuggestedPromptsItemMax))
            .max(signalsScoutEmitReportBodySuggestedPromptsMax)
            .optional()
            .describe(
                "Optional follow-up questions to offer above the report's `Ask AI` box. The reader clicks one to fill the box with it, then sends or edits it. Write the questions your own research left open, phrased as the reader would ask them."
            ),
    })
    .describe('Request body for `emit-report`. Run attribution is taken from the URL path.')

/**
 * Fire `emit_signal` with `source_product = signals_scout`. The `finding_id` is baked into the deterministic `Signal.source_id = run:<id>:finding:<id>` for traceability, but this is NOT idempotent — a second call with the same `finding_id` emits a second signal, so do not retry an emit that may have already succeeded.
 * @summary Emit a finding for a run
 */
export const signalsScoutEmitSignalBodyDescriptionMax = 50000

export const signalsScoutEmitSignalBodyConfidenceMin = 0
export const signalsScoutEmitSignalBodyConfidenceMax = 1

export const signalsScoutEmitSignalBodyEvidenceMax = 20

export const signalsScoutEmitSignalBodyTagsItemMax = 50

export const signalsScoutEmitSignalBodyTagsMax = 10

export const signalsScoutEmitSignalBodyFindingIdMax = 100

export const SignalsScoutEmitSignalBody = /* @__PURE__ */ zod
    .object({
        description: zod
            .string()
            .max(signalsScoutEmitSignalBodyDescriptionMax)
            .describe("Canonical evidence-bundle prose. Becomes the signal's `description`."),
        confidence: zod
            .number()
            .min(signalsScoutEmitSignalBodyConfidenceMin)
            .max(signalsScoutEmitSignalBodyConfidenceMax)
            .describe("Agent's confidence the finding is real in [0, 1]. Persisted in `extra`."),
        evidence: zod
            .array(
                zod
                    .object({
                        source_product: zod
                            .string()
                            .describe(
                                'Source the citation came from (`error_tracking`, `session_replay`, `logs`, ...).'
                            ),
                        summary: zod
                            .string()
                            .describe('One-sentence prose about why this evidence supports the finding.'),
                        entity_id: zod
                            .string()
                            .nullish()
                            .describe('Optional ID of the cited entity (issue id, recording id, log query id).'),
                    })
                    .describe('One citation attached to a finding. Mirrors `SignalsScoutEvidenceEntry`.')
            )
            .max(signalsScoutEmitSignalBodyEvidenceMax)
            .describe('Citations supporting the finding. Capped at 20 entries.'),
        hypothesis: zod.string().nullish().describe('Optional one-line hypothesis the finding tests.'),
        severity: zod
            .union([
                zod
                    .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                    .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Optional severity tag — one of P0, P1, P2, P3, P4. Informational only.\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
            ),
        dedupe_keys: zod
            .array(zod.string())
            .optional()
            .describe('Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`).'),
        tags: zod
            .array(zod.string().max(signalsScoutEmitSignalBodyTagsItemMax))
            .max(signalsScoutEmitSignalBodyTagsMax)
            .optional()
            .describe(
                "Optional category tags as lowercase kebab-case slugs (e.g. `cost-spike`, `silent-failure`), max 10. Reuse the vocabulary in your `tags:<domain>:taxonomy` scratchpad entry when a tag fits; coin a new slug when a genuinely new category emerges. Near-miss formats are normalized to slugs; persisted in the signal's `extra.tags` and on the emission row."
            ),
        time_range: zod
            .union([
                zod.object({
                    date_from: zod.string().describe("ISO-8601 inclusive lower bound for the finding's window."),
                    date_to: zod.string().describe("ISO-8601 inclusive upper bound for the finding's window."),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Optional time window the finding refers to.'),
        mcp_trace_id: zod.string().nullish().describe('Optional MCP trace id for cross-system debugging.'),
        finding_id: zod
            .string()
            .max(signalsScoutEmitSignalBodyFindingIdMax)
            .nullish()
            .describe(
                "Stable id for this finding, baked into the signal's source_id for traceability. NOT a dedupe key — re-emitting the same id creates another signal."
            ),
    })
    .describe('Request body for `emit-finding`. Run attribution is taken from the URL path.')

/**
 * The structured-output channel: record schema-validated records this run produced. Opt-in via the scout config's `structured_output_schema` (a JSON Schema describing one record) — without it the call fails closed, as it does for a dry-run scout (emit off). All-or-nothing: any invalid record fails the whole call with nothing written, so fix and resubmit the batch. Each accepted record lands in the project's event stream as a `$scout_structured_output` event — query them like any event (insights, SQL over `events`). Recording is idempotent: event ids are deterministic, so resubmitting an identical batch (e.g. retrying after a 503) cannot double-count.
 * @summary Record structured output for a run
 */
export const signalsScoutRecordOutputBodyRecordsItemSubjectMax = 200

export const signalsScoutRecordOutputBodyRecordsMax = 100

export const SignalsScoutRecordOutputBody = /* @__PURE__ */ zod
    .object({
        records: zod
            .array(
                zod
                    .object({
                        payload: zod
                            .record(zod.string(), zod.unknown())
                            .describe(
                                "The record itself, as a JSON object. Must validate against the scout config's `structured_output_schema` (shown in the run prompt); any invalid record fails the whole call with nothing written."
                            ),
                        subject: zod
                            .string()
                            .max(signalsScoutRecordOutputBodyRecordsItemSubjectMax)
                            .nullish()
                            .describe(
                                "Optional key naming what this record is about — a report id, URL, account key — so per-entity lookups don't need to parse `payload`. Omit for a run-level record."
                            ),
                    })
                    .describe('One record submitted through `scout-record-output`.')
            )
            .min(1)
            .max(signalsScoutRecordOutputBodyRecordsMax)
            .describe(
                "Records to record, each validated against the scout config's `structured_output_schema`. All-or-nothing: if any record fails validation, nothing is written and the error names the failing records. Capped at 100 per call; batch per-entity judgments rather than calling once per record."
            ),
    })
    .describe('Request body for `scout-record-output`: a batch of schema-validated records.')

/**
 * Batched form of the per-run emissions endpoint: return the findings every requested `SignalScoutRun` emitted, flattened newest-first, in a single request. Each row carries its `run_id`, so the caller can regroup by run. The findings UI uses this to load the whole recent window in one round-trip instead of one request per run. Strictly team-scoped — run ids belonging to another team contribute no rows (no per-run 404; one stale id never fails the batch).
 * @summary List emitted findings for many runs at once
 */
export const signalsScoutRunsEmissionsBatchBodyRunIdsMax = 200

export const SignalsScoutRunsEmissionsBatchBody = /* @__PURE__ */ zod
    .object({
        run_ids: zod
            .array(zod.uuid())
            .max(signalsScoutRunsEmissionsBatchBodyRunIdsMax)
            .describe(
                'UUIDs of the `SignalScoutRun` rows to resolve in one batch. Run ids belonging to another team are silently ignored (they contribute no rows) rather than failing the whole request. Capped at 200 ids per call.'
            ),
    })
    .describe(
        "Request body for the batched emissions \/ emission-reports lookups: the set of run UUIDs to\nresolve in one call. Collapses the findings UI's old per-run fan-out (one request — and for the\nreports lookup, one ClickHouse round-trip — per emitted run) into a single request."
    )

/**
 * Batched form of the per-run emission-reports endpoint. For every finding the requested runs emitted, resolve the inbox `SignalReport` (if any) its signal grouped into — all in a single ClickHouse round-trip rather than one query per run, which is what made the findings page slow to open. `report` is null when a finding hasn't grouped yet, was de-duplicated, or its signal was deleted. Strictly team-scoped — run ids belonging to another team contribute no rows.
 * @summary List the inbox reports many runs' findings linked to
 */
export const signalsScoutRunsEmissionReportsBatchBodyRunIdsMax = 200

export const SignalsScoutRunsEmissionReportsBatchBody = /* @__PURE__ */ zod
    .object({
        run_ids: zod
            .array(zod.uuid())
            .max(signalsScoutRunsEmissionReportsBatchBodyRunIdsMax)
            .describe(
                'UUIDs of the `SignalScoutRun` rows to resolve in one batch. Run ids belonging to another team are silently ignored (they contribute no rows) rather than failing the whole request. Capped at 200 ids per call.'
            ),
    })
    .describe(
        "Request body for the batched emissions \/ emission-reports lookups: the set of run UUIDs to\nresolve in one call. Collapses the findings UI's old per-run fan-out (one request — and for the\nreports lookup, one ClickHouse round-trip — per emitted run) into a single request."
    )

/**
 * Upsert a memory keyed on `(team, key)`. Re-using a key updates the existing entry in place. A write carries the entry's whole state, so `expires_at` is set when passed and cleared when omitted.
 * @summary Remember a scratchpad entry
 */
export const signalsScoutScratchpadRememberBodyKeyMax = 300

export const signalsScoutScratchpadRememberBodyContentMax = 50000

export const SignalsScoutScratchpadRememberBody = /* @__PURE__ */ zod
    .object({
        key: zod
            .string()
            .max(signalsScoutScratchpadRememberBodyKeyMax)
            .describe(
                "Agent-chosen semantic key, unique per team; re-using a key overwrites the entry in place. Key off the \*stable identity\* of what you're tracking — never embed a date, timestamp, or run id (that mints a new row every run and breaks dedupe). For run state\/cursors, use one fixed key and keep the timestamp in `content`."
            ),
        content: zod
            .string()
            .max(signalsScoutScratchpadRememberBodyContentMax)
            .describe('Prose to write. Read verbatim into future prompts.'),
        run_id: zod
            .uuid()
            .nullish()
            .describe(
                "Run that authored this memory; persisted as `created_by_run_id` for lineage. Best-effort — a `run_id` that isn't a run on this project is dropped (lineage left null), not rejected, so the memory write is never lost."
            ),
        expires_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe(
                "Optional ISO-8601 expiry for a memory that's only true for a while (a cooldown, a window you're watching). After this time the entry drops out of searches, so you don't have to come back and forget it. Omit for a durable memory — every write sets the whole entry, so omitting it on a later write clears an expiry set earlier."
            ),
    })
    .describe('Request body for `remember`.')

/**
 * Delete an entry by key. Returns `deleted=false` if no row matched.
 * @summary Forget a scratchpad entry by key
 */
export const signalsScoutScratchpadForgetBodyKeyMax = 300

export const SignalsScoutScratchpadForgetBody = /* @__PURE__ */ zod
    .object({
        key: zod.string().max(signalsScoutScratchpadForgetBodyKeyMax).describe('Memory key to delete.'),
    })
    .describe('Request body for `forget`.')

export const SignalsSourceConfigsCreateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'jira',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
            'signals_scout',
            'logs',
            'health_checks',
            'endpoints',
            'replay_vision',
            'analytics',
            'freshdesk',
            'freshservice',
            'front',
            'gorgias',
            'kustomer',
            'dixa',
            'plain',
            'gitlab',
            'gitea',
            'shortcut',
            'sentry',
            'rollbar',
            'bugsnag',
            'honeybadger',
            'raygun',
            'snyk',
            'sonarqube',
            'semgrep',
            'rapid7_insightvm',
            'featurebase',
            'frill',
            'aha',
            'uservoice',
            'productboard',
            'canny',
            'asknicely',
            'retently',
            'appfigures',
            'appfollow',
            'judgeme_reviews',
            'intercom',
            'hubspot',
            'engineering_analytics',
            'google_search_console',
        ])
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `jira` - Jira\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints\n\* `replay_vision` - Replay Vision\n\* `analytics` - Product analytics\n\* `freshdesk` - Freshdesk\n\* `freshservice` - Freshservice\n\* `front` - Front\n\* `gorgias` - Gorgias\n\* `kustomer` - Kustomer\n\* `dixa` - Dixa\n\* `plain` - Plain\n\* `gitlab` - GitLab\n\* `gitea` - Gitea\n\* `shortcut` - Shortcut\n\* `sentry` - Sentry\n\* `rollbar` - Rollbar\n\* `bugsnag` - Bugsnag\n\* `honeybadger` - Honeybadger\n\* `raygun` - Raygun\n\* `snyk` - Snyk\n\* `sonarqube` - SonarQube\n\* `semgrep` - Semgrep\n\* `rapid7_insightvm` - Rapid7 InsightVM\n\* `featurebase` - Featurebase\n\* `frill` - Frill\n\* `aha` - Aha\n\* `uservoice` - UserVoice\n\* `productboard` - Productboard\n\* `canny` - Canny\n\* `asknicely` - AskNicely\n\* `retently` - Retently\n\* `appfigures` - Appfigures\n\* `appfollow` - AppFollow\n\* `judgeme_reviews` - Judge.me\n\* `intercom` - Intercom\n\* `hubspot` - HubSpot\n\* `engineering_analytics` - Engineering analytics\n\* `google_search_console` - Google Search Console'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation_report',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
            'cross_source_issue',
            'alert_state_change',
            'health_issue',
            'endpoint_execution_failed',
            'endpoint_breakdown_limit_exceeded',
            'scanner_finding',
            'anomaly_investigation',
            'feedback',
            'review',
            'ci_flaky_check',
            'ci_broken_default_branch',
            'ci_duration_regression',
            'search_opportunity',
        ])
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation_report` - Evaluation report\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n\* `scanner_finding` - Scanner finding\n\* `anomaly_investigation` - Anomaly investigation\n\* `feedback` - Feedback\n\* `review` - Review\n\* `ci_flaky_check` - CI flaky check\n\* `ci_broken_default_branch` - CI broken default branch\n\* `ci_duration_regression` - CI duration regression\n\* `search_opportunity` - Search opportunity'
        ),
    enabled: zod.boolean().optional(),
    config: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Per-source settings as a JSON object. Keys read by the emission actionability gate on sources that define one (most data warehouse imports, and Conversations): `steering` (string, max 2000 characters) holds the team's preferences about this source's records in plain language: what matters, what to skip, what's out of scope. The emission actionability gate applies it when deciding which records become signals; rules apply from the next sync and nothing already emitted is retracted. `default_not_actionable` (boolean, default false) flips the gate's default: instead of keeping every record the steering rules don't exclude, only records that clearly match the team's preferences are kept. Other sources store these keys without reading them yet; future pipeline stages will consume the same steering text. Some sources read additional keys, for example `recording_filters` and `sample_rate` for session analysis."
        ),
})

export const SignalsSourceConfigsUpdateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'jira',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
            'signals_scout',
            'logs',
            'health_checks',
            'endpoints',
            'replay_vision',
            'analytics',
            'freshdesk',
            'freshservice',
            'front',
            'gorgias',
            'kustomer',
            'dixa',
            'plain',
            'gitlab',
            'gitea',
            'shortcut',
            'sentry',
            'rollbar',
            'bugsnag',
            'honeybadger',
            'raygun',
            'snyk',
            'sonarqube',
            'semgrep',
            'rapid7_insightvm',
            'featurebase',
            'frill',
            'aha',
            'uservoice',
            'productboard',
            'canny',
            'asknicely',
            'retently',
            'appfigures',
            'appfollow',
            'judgeme_reviews',
            'intercom',
            'hubspot',
            'engineering_analytics',
            'google_search_console',
        ])
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `jira` - Jira\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints\n\* `replay_vision` - Replay Vision\n\* `analytics` - Product analytics\n\* `freshdesk` - Freshdesk\n\* `freshservice` - Freshservice\n\* `front` - Front\n\* `gorgias` - Gorgias\n\* `kustomer` - Kustomer\n\* `dixa` - Dixa\n\* `plain` - Plain\n\* `gitlab` - GitLab\n\* `gitea` - Gitea\n\* `shortcut` - Shortcut\n\* `sentry` - Sentry\n\* `rollbar` - Rollbar\n\* `bugsnag` - Bugsnag\n\* `honeybadger` - Honeybadger\n\* `raygun` - Raygun\n\* `snyk` - Snyk\n\* `sonarqube` - SonarQube\n\* `semgrep` - Semgrep\n\* `rapid7_insightvm` - Rapid7 InsightVM\n\* `featurebase` - Featurebase\n\* `frill` - Frill\n\* `aha` - Aha\n\* `uservoice` - UserVoice\n\* `productboard` - Productboard\n\* `canny` - Canny\n\* `asknicely` - AskNicely\n\* `retently` - Retently\n\* `appfigures` - Appfigures\n\* `appfollow` - AppFollow\n\* `judgeme_reviews` - Judge.me\n\* `intercom` - Intercom\n\* `hubspot` - HubSpot\n\* `engineering_analytics` - Engineering analytics\n\* `google_search_console` - Google Search Console'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation_report',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
            'cross_source_issue',
            'alert_state_change',
            'health_issue',
            'endpoint_execution_failed',
            'endpoint_breakdown_limit_exceeded',
            'scanner_finding',
            'anomaly_investigation',
            'feedback',
            'review',
            'ci_flaky_check',
            'ci_broken_default_branch',
            'ci_duration_regression',
            'search_opportunity',
        ])
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation_report` - Evaluation report\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n\* `scanner_finding` - Scanner finding\n\* `anomaly_investigation` - Anomaly investigation\n\* `feedback` - Feedback\n\* `review` - Review\n\* `ci_flaky_check` - CI flaky check\n\* `ci_broken_default_branch` - CI broken default branch\n\* `ci_duration_regression` - CI duration regression\n\* `search_opportunity` - Search opportunity'
        ),
    enabled: zod.boolean().optional(),
    config: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Per-source settings as a JSON object. Keys read by the emission actionability gate on sources that define one (most data warehouse imports, and Conversations): `steering` (string, max 2000 characters) holds the team's preferences about this source's records in plain language: what matters, what to skip, what's out of scope. The emission actionability gate applies it when deciding which records become signals; rules apply from the next sync and nothing already emitted is retracted. `default_not_actionable` (boolean, default false) flips the gate's default: instead of keeping every record the steering rules don't exclude, only records that clearly match the team's preferences are kept. Other sources store these keys without reading them yet; future pipeline stages will consume the same steering text. Some sources read additional keys, for example `recording_filters` and `sample_rate` for session analysis."
        ),
})

export const SignalsSourceConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'jira',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
            'signals_scout',
            'logs',
            'health_checks',
            'endpoints',
            'replay_vision',
            'analytics',
            'freshdesk',
            'freshservice',
            'front',
            'gorgias',
            'kustomer',
            'dixa',
            'plain',
            'gitlab',
            'gitea',
            'shortcut',
            'sentry',
            'rollbar',
            'bugsnag',
            'honeybadger',
            'raygun',
            'snyk',
            'sonarqube',
            'semgrep',
            'rapid7_insightvm',
            'featurebase',
            'frill',
            'aha',
            'uservoice',
            'productboard',
            'canny',
            'asknicely',
            'retently',
            'appfigures',
            'appfollow',
            'judgeme_reviews',
            'intercom',
            'hubspot',
            'engineering_analytics',
            'google_search_console',
        ])
        .optional()
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `jira` - Jira\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints\n\* `replay_vision` - Replay Vision\n\* `analytics` - Product analytics\n\* `freshdesk` - Freshdesk\n\* `freshservice` - Freshservice\n\* `front` - Front\n\* `gorgias` - Gorgias\n\* `kustomer` - Kustomer\n\* `dixa` - Dixa\n\* `plain` - Plain\n\* `gitlab` - GitLab\n\* `gitea` - Gitea\n\* `shortcut` - Shortcut\n\* `sentry` - Sentry\n\* `rollbar` - Rollbar\n\* `bugsnag` - Bugsnag\n\* `honeybadger` - Honeybadger\n\* `raygun` - Raygun\n\* `snyk` - Snyk\n\* `sonarqube` - SonarQube\n\* `semgrep` - Semgrep\n\* `rapid7_insightvm` - Rapid7 InsightVM\n\* `featurebase` - Featurebase\n\* `frill` - Frill\n\* `aha` - Aha\n\* `uservoice` - UserVoice\n\* `productboard` - Productboard\n\* `canny` - Canny\n\* `asknicely` - AskNicely\n\* `retently` - Retently\n\* `appfigures` - Appfigures\n\* `appfollow` - AppFollow\n\* `judgeme_reviews` - Judge.me\n\* `intercom` - Intercom\n\* `hubspot` - HubSpot\n\* `engineering_analytics` - Engineering analytics\n\* `google_search_console` - Google Search Console'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation_report',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
            'cross_source_issue',
            'alert_state_change',
            'health_issue',
            'endpoint_execution_failed',
            'endpoint_breakdown_limit_exceeded',
            'scanner_finding',
            'anomaly_investigation',
            'feedback',
            'review',
            'ci_flaky_check',
            'ci_broken_default_branch',
            'ci_duration_regression',
            'search_opportunity',
        ])
        .optional()
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation_report` - Evaluation report\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n\* `scanner_finding` - Scanner finding\n\* `anomaly_investigation` - Anomaly investigation\n\* `feedback` - Feedback\n\* `review` - Review\n\* `ci_flaky_check` - CI flaky check\n\* `ci_broken_default_branch` - CI broken default branch\n\* `ci_duration_regression` - CI duration regression\n\* `search_opportunity` - Search opportunity'
        ),
    enabled: zod.boolean().optional(),
    config: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Per-source settings as a JSON object. Keys read by the emission actionability gate on sources that define one (most data warehouse imports, and Conversations): `steering` (string, max 2000 characters) holds the team's preferences about this source's records in plain language: what matters, what to skip, what's out of scope. The emission actionability gate applies it when deciding which records become signals; rules apply from the next sync and nothing already emitted is retracted. `default_not_actionable` (boolean, default false) flips the gate's default: instead of keeping every record the steering rules don't exclude, only records that clearly match the team's preferences are kept. Other sources store these keys without reading them yet; future pipeline stages will consume the same steering text. Some sources read additional keys, for example `recording_filters` and `sample_rate` for session analysis."
        ),
})

/**
 * Per-user signal autonomy config (singleton keyed by user).
 *
 * GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
 * POST   /api/users/<id>/signal_autonomy/ → create or update
 * DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const usersSignalAutonomyCreateBodySlackNotificationChannelMax = 255

export const UsersSignalAutonomyCreateBody = /* @__PURE__ */ zod.object({
    autostart_priority: zod
        .union([
            zod
                .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    slack_notification_channel: zod
        .string()
        .max(usersSignalAutonomyCreateBodySlackNotificationChannelMax)
        .nullish()
        .describe(
            'Slack channel target in the same `channel_id|#channel-name` shape PostHog uses elsewhere (only the channel id is required). Null disables Slack notifications.'
        ),
    slack_notification_min_priority: zod
        .union([
            zod
                .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'Minimum report priority that triggers a Slack notification. P0 is highest. Null means notify on every priority (and reports without a priority judgment).\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
        ),
})
