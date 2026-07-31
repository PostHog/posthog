/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const VisionActionTriggerTypeEnumApi = zod
    .enum(['schedule', 'threshold'])
    .describe('\* `schedule` - Schedule\n\* `threshold` - Threshold')

export type VisionActionTriggerTypeEnumApi = zod.input<typeof VisionActionTriggerTypeEnumApi>
export type VisionActionTriggerTypeEnumApiOutput = zod.output<typeof VisionActionTriggerTypeEnumApi>

export const VisionActionModeEnumApi = zod
    .enum(['group_summary', 'alert', 'per_observation'])
    .describe('\* `group_summary` - Group summary\n\* `alert` - Alert\n\* `per_observation` - Per observation')

export type VisionActionModeEnumApi = zod.input<typeof VisionActionModeEnumApi>
export type VisionActionModeEnumApiOutput = zod.output<typeof VisionActionModeEnumApi>

export const triggerConfigApiTimezoneDefault = `UTC`

export const TriggerConfigApi = zod
    .object({
        rrule: zod
            .string()
            .optional()
            .describe(
                'iCal RRULE string controlling the schedule cadence (no DTSTART — the start is managed separately).'
            ),
        timezone: zod
            .string()
            .default(triggerConfigApiTimezoneDefault)
            .describe("IANA timezone name the RRULE is expanded in, e.g. 'Europe\/Prague'. Defaults to 'UTC'."),
    })
    .describe('Schedule trigger parameters. Threshold triggers are reserved and rejected at the API for now.')

export type TriggerConfigApi = zod.input<typeof TriggerConfigApi>
export type TriggerConfigApiOutput = zod.output<typeof TriggerConfigApi>

export const VerdictEnumApi = zod
    .enum(['yes', 'no', 'inconclusive'])
    .describe('\* `yes` - yes\n\* `no` - no\n\* `inconclusive` - inconclusive')

export type VerdictEnumApi = zod.input<typeof VerdictEnumApi>
export type VerdictEnumApiOutput = zod.output<typeof VerdictEnumApi>

export const SelectionApi = zod
    .object({
        scanner_ids: zod
            .array(zod.string())
            .optional()
            .describe('Restrict to observations produced by these scanner IDs. Defaults to the bound scanner.'),
        verdict: zod
            .array(VerdictEnumApi)
            .optional()
            .describe('Only run on monitor observations with one of these verdicts (yes\/no\/inconclusive).'),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Only run on classifier observations carrying any of these tags (fixed or freeform).'),
        min_score: zod
            .number()
            .optional()
            .describe('Only run on scorer observations with a score at or above this value (inclusive).'),
        max_score: zod
            .number()
            .optional()
            .describe('Only run on scorer observations with a score at or below this value (inclusive).'),
    })
    .describe(
        'The action\'s targeting predicate (\"run this on…\") applied when gathering observations. All keys\noptional; this typed shape is the allowlist, so unknown input keys are dropped rather than persisted.'
    )

export type SelectionApi = zod.input<typeof SelectionApi>
export type SelectionApiOutput = zod.output<typeof SelectionApi>

export const synthesisConfigApiPromptGuideMax = 500

export const SynthesisConfigApi = zod
    .object({
        prompt_guide: zod
            .string()
            .max(synthesisConfigApiPromptGuideMax)
            .optional()
            .describe('Free-form guidance steering how the group summary is written.'),
    })
    .describe('Options for the group-summary synthesis step.')

export type SynthesisConfigApi = zod.input<typeof SynthesisConfigApi>
export type SynthesisConfigApiOutput = zod.output<typeof SynthesisConfigApi>

export const AlertConfigFrequencyEnumApi = zod
    .enum(['every_match', 'on_breach'])
    .describe('\* `every_match` - Every new match\n\* `on_breach` - When a threshold is crossed')

export type AlertConfigFrequencyEnumApi = zod.input<typeof AlertConfigFrequencyEnumApi>
export type AlertConfigFrequencyEnumApiOutput = zod.output<typeof AlertConfigFrequencyEnumApi>

export const VisionAlertMetricEnumApi = zod
    .enum(['count', 'avg_score'])
    .describe('\* `count` - Count of matching observations\n\* `avg_score` - Average score')

export type VisionAlertMetricEnumApi = zod.input<typeof VisionAlertMetricEnumApi>
export type VisionAlertMetricEnumApiOutput = zod.output<typeof VisionAlertMetricEnumApi>

export const VisionAlertDirectionEnumApi = zod
    .enum(['above', 'below'])
    .describe('\* `above` - At or above\n\* `below` - At or below')

export type VisionAlertDirectionEnumApi = zod.input<typeof VisionAlertDirectionEnumApi>
export type VisionAlertDirectionEnumApiOutput = zod.output<typeof VisionAlertDirectionEnumApi>

export const WindowDaysEnumApi = zod
    .union([zod.literal(1), zod.literal(3), zod.literal(7), zod.literal(14), zod.literal(30)])
    .describe('\* `1` - 1 day\n\* `3` - 3 days\n\* `7` - 7 days\n\* `14` - 14 days\n\* `30` - 30 days')

export type WindowDaysEnumApi = zod.input<typeof WindowDaysEnumApi>
export type WindowDaysEnumApiOutput = zod.output<typeof WindowDaysEnumApi>

export const alertConfigApiFrequencyDefault = `on_breach`
export const alertConfigApiMetricDefault = `count`
export const alertConfigApiDirectionDefault = `above`

export const AlertConfigApi = zod
    .object({
        frequency: AlertConfigFrequencyEnumApi.default(alertConfigApiFrequencyDefault).describe(
            "'every_match' notifies about every new matching observation (batched per check); 'on_breach' notifies once when the threshold condition starts holding. Defaults to 'on_breach'.\n\n\* `every_match` - Every new match\n\* `on_breach` - When a threshold is crossed"
        ),
        metric: VisionAlertMetricEnumApi.default(alertConfigApiMetricDefault).describe(
            "What to measure over the window: 'count' of targeted observations, or 'avg_score' (the mean scorer score; scorer scanners only). every_match supports 'count' only.\n\n\* `count` - Count of matching observations\n\* `avg_score` - Average score"
        ),
        threshold: zod
            .number()
            .optional()
            .describe(
                "The alert fires when the metric is at or above ('above') or at or below ('below') this value, per 'direction'. Required for on_breach; ignored for every_match."
            ),
        direction: VisionAlertDirectionEnumApi.default(alertConfigApiDirectionDefault).describe(
            "Which side of the threshold breaches: 'above' fires when the metric is at or above it, 'below' when at or below (e.g. an average score dropping under a floor). Both inclusive. Defaults to 'above'; ignored for every_match.\n\n\* `above` - At or above\n\* `below` - At or below"
        ),
        window_days: WindowDaysEnumApi.optional().describe(
            "Rolling lookback window for on_breach conditions, ending at each check. Defaults to 1 day. every_match ignores it (each check covers what's new since the previous one).\n\n\* `1` - 1 day\n\* `3` - 3 days\n\* `7` - 7 days\n\* `14` - 14 days\n\* `30` - 30 days"
        ),
    })
    .describe(
        "The alert condition for mode='alert', applied after `selection` targeting. 'every_match'\nnotifies about each new match since the previous check; 'on_breach' compares a metric to a\nthreshold over a rolling window and notifies on the transition into breach."
    )

export type AlertConfigApi = zod.input<typeof AlertConfigApi>
export type AlertConfigApiOutput = zod.output<typeof AlertConfigApi>

export const DeliveryTargetTypeEnumApi = zod
    .enum(['slack', 'webhook'])
    .describe('\* `slack` - Slack\n\* `webhook` - Webhook')

export type DeliveryTargetTypeEnumApi = zod.input<typeof DeliveryTargetTypeEnumApi>
export type DeliveryTargetTypeEnumApiOutput = zod.output<typeof DeliveryTargetTypeEnumApi>

export const DeliveryTargetApi = zod
    .object({
        type: DeliveryTargetTypeEnumApi.describe(
            "Destination type: 'slack' posts to a Slack channel; 'webhook' POSTs a JSON payload to a URL.\n\n\* `slack` - Slack\n\* `webhook` - Webhook"
        ),
        integration_id: zod
            .number()
            .optional()
            .describe("ID of the Slack Integration on this team used to deliver. Required when type is 'slack'."),
        channel: zod
            .string()
            .optional()
            .describe("Slack channel ID or name the summary is posted to. Required when type is 'slack'."),
        url: zod
            .url()
            .optional()
            .describe(
                "HTTPS endpoint the summary is POSTed to as JSON. Required when type is 'webhook'. Redacted to scheme+host in responses for users without editor access to the scanner."
            ),
    })
    .describe('A single delivery destination: a Slack channel or an HTTP webhook URL.')

export type DeliveryTargetApi = zod.input<typeof DeliveryTargetApi>
export type DeliveryTargetApiOutput = zod.output<typeof DeliveryTargetApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const visionActionApiNameMax = 255

export const VisionActionApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(visionActionApiNameMax).describe('Human-readable action name. Unique within the team.'),
        scanner: zod
            .uuid()
            .describe('Scanner whose observations this action operates on. Must belong to the same team.'),
        enabled: zod.boolean().optional().describe('When false, the scheduler skips this action.'),
        is_scanner_digest: zod
            .boolean()
            .optional()
            .describe(
                "Marks this action as the scanner's built-in daily digest, the one summary surfaced on the scanner overview. At most one digest per scanner."
            ),
        trigger_type: VisionActionTriggerTypeEnumApi.optional().describe(
            "What fires the action. MVP supports 'schedule' only.\n\n\* `schedule` - Schedule\n\* `threshold` - Threshold"
        ),
        mode: VisionActionModeEnumApi.optional().describe(
            "What the action produces. MVP supports 'group_summary' only.\n\n\* `group_summary` - Group summary\n\* `alert` - Alert\n\* `per_observation` - Per observation"
        ),
        trigger_config: TriggerConfigApi.optional().describe(
            'Trigger parameters. For schedule triggers: {rrule, timezone}.'
        ),
        selection: SelectionApi.optional().describe(
            "Targeting predicate: which of the scanner's observations this action runs on."
        ),
        synthesis_config: SynthesisConfigApi.optional().describe(
            'Synthesis options for the group summary, e.g. {prompt_guide}.'
        ),
        alert_config: AlertConfigApi.optional().describe(
            "Alert condition; required when mode is 'alert', ignored otherwise."
        ),
        delivery_config: zod
            .array(DeliveryTargetApi)
            .optional()
            .describe('List of delivery destinations the synthesized summary is sent to.'),
        next_run_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('Computed next fire time for schedule triggers; the scheduler scans this.'),
        last_run_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('Timestamp of the most recent run, or null if it has never run.'),
        hog_flow_id: zod
            .uuid()
            .nullable()
            .describe('ID of the delivery flow provisioned for this action. Null until delivery is wired up.'),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created the action.'),
        updated_at: zod.iso.datetime({ offset: true }),
    })
    .describe('A Replay Vision action: a scheduled \"and then…\" automation over a scanner\'s observations.')

export type VisionActionApi = zod.input<typeof VisionActionApi>
export type VisionActionApiOutput = zod.output<typeof VisionActionApi>

export const PaginatedVisionActionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(VisionActionApi),
})

export type PaginatedVisionActionListApi = zod.input<typeof PaginatedVisionActionListApi>
export type PaginatedVisionActionListApiOutput = zod.output<typeof PaginatedVisionActionListApi>

export const patchedVisionActionApiNameMax = 255

export const PatchedVisionActionApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod
            .string()
            .max(patchedVisionActionApiNameMax)
            .optional()
            .describe('Human-readable action name. Unique within the team.'),
        scanner: zod
            .uuid()
            .optional()
            .describe('Scanner whose observations this action operates on. Must belong to the same team.'),
        enabled: zod.boolean().optional().describe('When false, the scheduler skips this action.'),
        is_scanner_digest: zod
            .boolean()
            .optional()
            .describe(
                "Marks this action as the scanner's built-in daily digest, the one summary surfaced on the scanner overview. At most one digest per scanner."
            ),
        trigger_type: VisionActionTriggerTypeEnumApi.optional().describe(
            "What fires the action. MVP supports 'schedule' only.\n\n\* `schedule` - Schedule\n\* `threshold` - Threshold"
        ),
        mode: VisionActionModeEnumApi.optional().describe(
            "What the action produces. MVP supports 'group_summary' only.\n\n\* `group_summary` - Group summary\n\* `alert` - Alert\n\* `per_observation` - Per observation"
        ),
        trigger_config: TriggerConfigApi.optional().describe(
            'Trigger parameters. For schedule triggers: {rrule, timezone}.'
        ),
        selection: SelectionApi.optional().describe(
            "Targeting predicate: which of the scanner's observations this action runs on."
        ),
        synthesis_config: SynthesisConfigApi.optional().describe(
            'Synthesis options for the group summary, e.g. {prompt_guide}.'
        ),
        alert_config: AlertConfigApi.optional().describe(
            "Alert condition; required when mode is 'alert', ignored otherwise."
        ),
        delivery_config: zod
            .array(DeliveryTargetApi)
            .optional()
            .describe('List of delivery destinations the synthesized summary is sent to.'),
        next_run_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Computed next fire time for schedule triggers; the scheduler scans this.'),
        last_run_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Timestamp of the most recent run, or null if it has never run.'),
        hog_flow_id: zod
            .uuid()
            .nullish()
            .describe('ID of the delivery flow provisioned for this action. Null until delivery is wired up.'),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: zod.union([UserBasicApi, zod.null()]).optional().describe('User who created the action.'),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
    })
    .describe('A Replay Vision action: a scheduled \"and then…\" automation over a scanner\'s observations.')

export type PatchedVisionActionApi = zod.input<typeof PatchedVisionActionApi>
export type PatchedVisionActionApiOutput = zod.output<typeof PatchedVisionActionApi>

export const RunActionResponseApi = zod
    .object({
        workflow_id: zod
            .string()
            .describe("Temporal workflow id for the run; the resulting run appears under the action's run history."),
        already_running: zod
            .boolean()
            .describe(
                'True when a run for this action was already in progress (scheduled or manual), so this request coalesced onto it rather than starting a second run.'
            ),
    })
    .describe('Async-accepted response for POST \/vision\/actions\/{id}\/run\/.')

export type RunActionResponseApi = zod.input<typeof RunActionResponseApi>
export type RunActionResponseApiOutput = zod.output<typeof RunActionResponseApi>

export const VisionActionRunStatusEnumApi = zod
    .enum(['running', 'completed', 'failed', 'skipped'])
    .describe('\* `running` - Running\n\* `completed` - Completed\n\* `failed` - Failed\n\* `skipped` - Skipped')

export type VisionActionRunStatusEnumApi = zod.input<typeof VisionActionRunStatusEnumApi>
export type VisionActionRunStatusEnumApiOutput = zod.output<typeof VisionActionRunStatusEnumApi>

export const VisionActionRunListApi = zod
    .object({
        id: zod.uuid(),
        status: VisionActionRunStatusEnumApi.describe(
            'Run outcome: running, completed, failed, or skipped.\n\n\* `running` - Running\n\* `completed` - Completed\n\* `failed` - Failed\n\* `skipped` - Skipped'
        ),
        scheduled_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('The scheduled fire time this run was claimed for.'),
        observation_count: zod.number().describe("Number of observations that fed this run's summary."),
        error_reason: zod
            .string()
            .nullable()
            .describe('Short human-readable reason a run skipped or failed; null on success.'),
        is_recovery: zod
            .boolean()
            .describe(
                "True for the run recording an alert's condition clearing after a breach (the recovery bookend in run history). False for alert firings and summaries."
            ),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
    })
    .describe("Lightweight run row for the per-action run list (no report body — that's fetched on retrieve).")

export type VisionActionRunListApi = zod.input<typeof VisionActionRunListApi>
export type VisionActionRunListApiOutput = zod.output<typeof VisionActionRunListApi>

export const PaginatedVisionActionRunListListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(VisionActionRunListApi),
})

export type PaginatedVisionActionRunListListApi = zod.input<typeof PaginatedVisionActionRunListListApi>
export type PaginatedVisionActionRunListListApiOutput = zod.output<typeof PaginatedVisionActionRunListListApi>

export const RunObservationApi = zod
    .object({
        index: zod
            .number()
            .describe(
                '1-based reference number of this observation in the summary, stable across deletions. The synthesized report cites observations by this number (rendered like `[3]`), so consumers use it to resolve a citation to its observation.'
            ),
        id: zod.uuid().describe('Observation id; links to the observation detail view.'),
        session_id: zod.string().describe('Session recording id this observation was made on.'),
        recording_subject_email: zod
            .string()
            .nullable()
            .describe('Email of the person in the recorded session, captured at scan time; null if unidentified.'),
        title: zod
            .string()
            .nullable()
            .describe("Short title from the observation's summary; null if the observation had none."),
        created_at: zod.iso.datetime({ offset: true }).describe('When the observation was produced.'),
    })
    .describe(
        "One recording an action run included in its summary — the 'recordings included' list on the run detail view."
    )

export type RunObservationApi = zod.input<typeof RunObservationApi>
export type RunObservationApiOutput = zod.output<typeof RunObservationApi>

export const VisionActionRunApi = zod
    .object({
        id: zod.uuid(),
        status: VisionActionRunStatusEnumApi.describe(
            'Run outcome: running, completed, failed, or skipped.\n\n\* `running` - Running\n\* `completed` - Completed\n\* `failed` - Failed\n\* `skipped` - Skipped'
        ),
        scheduled_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('The scheduled fire time this run was claimed for.'),
        observation_count: zod.number().describe("Number of observations that fed this run's summary."),
        error_reason: zod
            .string()
            .nullable()
            .describe('Short human-readable reason a run skipped or failed; null on success.'),
        is_recovery: zod
            .boolean()
            .describe(
                "True for the run recording an alert's condition clearing after a breach (the recovery bookend in run history). False for alert firings and summaries."
            ),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        synthesized_markdown: zod
            .string()
            .describe('The synthesized group-summary report in Markdown. Empty until a run completes successfully.'),
        observations: zod
            .array(RunObservationApi)
            .describe(
                'Recordings this run included in its summary, in summary order. Empty for runs recorded before this was tracked, and for skipped\/failed runs.'
            ),
    })
    .describe('Full run detail: the list fields plus the synthesized report and the recordings it summarized.')

export type VisionActionRunApi = zod.input<typeof VisionActionRunApi>
export type VisionActionRunApiOutput = zod.output<typeof VisionActionRunApi>

export const ObservationStatusEnumApi = zod
    .enum(['pending', 'running', 'succeeded', 'failed', 'ineligible'])
    .describe(
        '\* `pending` - Pending\n\* `running` - Running\n\* `succeeded` - Succeeded\n\* `failed` - Failed\n\* `ineligible` - Ineligible'
    )

export type ObservationStatusEnumApi = zod.input<typeof ObservationStatusEnumApi>
export type ObservationStatusEnumApiOutput = zod.output<typeof ObservationStatusEnumApi>

export const ScannerTypeEnumApi = zod
    .enum(['monitor', 'classifier', 'scorer', 'summarizer'])
    .describe(
        '\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
    )

export type ScannerTypeEnumApi = zod.input<typeof ScannerTypeEnumApi>
export type ScannerTypeEnumApiOutput = zod.output<typeof ScannerTypeEnumApi>

export const ScannerSnapshotApi = zod
    .object({
        name: zod.string().describe('Scanner name at run time.'),
        scanner_type: ScannerTypeEnumApi.describe(
            'Scanner type (monitor, classifier, scorer, summarizer) at run time.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
        ),
        scanner_version: zod
            .number()
            .describe('The `ReplayScanner.scanner_version` value at the moment the workflow ran.'),
        model: zod
            .string()
            .describe('Concrete model that ran the observation; historical rows may carry since-retired model ids.'),
        provider: zod
            .string()
            .describe('Concrete provider that ran the observation; historical rows may carry since-retired providers.'),
        emits_signals: zod.boolean().describe('Whether the observation was run with Signal emission enabled.'),
        scanner_config: zod
            .unknown()
            .describe('Scanner-type-specific configuration at run time (prompt, tags, scale, etc.).'),
    })
    .describe('Mirrors `temporal.types.ScannerSnapshot` for OpenAPI generation.')

export type ScannerSnapshotApi = zod.input<typeof ScannerSnapshotApi>
export type ScannerSnapshotApiOutput = zod.output<typeof ScannerSnapshotApi>

export const scannerResultApiSignalsCountMin = 0

export const ScannerResultApi = zod
    .object({
        model_output: zod
            .unknown()
            .describe(
                'Validated scanner output. Shape depends on `scanner_snapshot.scanner_type`; always carries `confidence` and `scanner_type`.'
            ),
        signals_count: zod
            .number()
            .min(scannerResultApiSignalsCountMin)
            .describe('Number of PostHog Signals emitted from this observation.'),
    })
    .describe('Mirrors `temporal.types.ScannerResult` for OpenAPI generation.')

export type ScannerResultApi = zod.input<typeof ScannerResultApi>
export type ScannerResultApiOutput = zod.output<typeof ScannerResultApi>

export const ObservationTriggerEnumApi = zod
    .enum(['schedule', 'on_demand', 'retry'])
    .describe('\* `schedule` - Schedule\n\* `on_demand` - On demand\n\* `retry` - Retry')

export type ObservationTriggerEnumApi = zod.input<typeof ObservationTriggerEnumApi>
export type ObservationTriggerEnumApiOutput = zod.output<typeof ObservationTriggerEnumApi>

export const replayObservationLabelApiFeedbackDefault = ``
export const replayObservationLabelApiFeedbackMax = 5000

export const ReplayObservationLabelApi = zod
    .object({
        is_correct: zod.boolean().describe('True if the scanner scored this session correctly, false if not.'),
        feedback: zod
            .string()
            .max(replayObservationLabelApiFeedbackMax)
            .default(replayObservationLabelApiFeedbackDefault)
            .describe(
                'Optional written context on the rating, for thumbs-up and thumbs-down alike: what the scanner got right or wrong, or what it should have concluded.'
            ),
    })
    .describe("The team's shared judgement on whether the scanner scored this session correctly.")

export type ReplayObservationLabelApi = zod.input<typeof ReplayObservationLabelApi>
export type ReplayObservationLabelApiOutput = zod.output<typeof ReplayObservationLabelApi>

export const ReplayObservationApi = zod.object({
    id: zod.uuid(),
    scanner_id: zod.uuid().describe('The scanner that produced this observation.'),
    session_id: zod.string().describe('Session recording id this scanner was applied to.'),
    status: ObservationStatusEnumApi.describe(
        'Observation status (pending, running, succeeded, failed, ineligible).\n\n\* `pending` - Pending\n\* `running` - Running\n\* `succeeded` - Succeeded\n\* `failed` - Failed\n\* `ineligible` - Ineligible'
    ),
    error_reason: zod
        .string()
        .describe(
            'Populated on terminal non-success statuses; formatted as `kind:human-readable message`. For `ineligible`, kind is one of no_recording \/ too_short \/ too_inactive \/ too_long \/ no_events. For `failed`, kind is one of provider_transient \/ provider_rejected \/ rasterization_failed \/ validation_failed \/ internal_error \/ orphaned.'
        ),
    workflow_id: zod
        .string()
        .describe('Temporal workflow id for progress queries and debugging. Empty until the workflow starts.'),
    scanner_snapshot: zod
        .union([ScannerSnapshotApi, zod.null()])
        .describe(
            'Frozen view of the scanner at run time; scanner edits do not retroactively mutate this observation.'
        ),
    scanner_result: zod
        .union([ScannerResultApi, zod.null()])
        .describe('Result data persisted on success; null until the observation succeeds.'),
    triggered_by: ObservationTriggerEnumApi.describe(
        'Whether this observation came from the schedule, an on-demand request, or a retry of a failed observation.\n\n\* `schedule` - Schedule\n\* `on_demand` - On demand\n\* `retry` - Retry'
    ),
    triggered_by_user: zod
        .union([UserBasicApi, zod.null()])
        .describe('User who triggered an on-demand observation; null for scheduled observations.'),
    distinct_id: zod
        .string()
        .nullable()
        .describe('Distinct id of the person in the recorded session (the subject being watched); null if unknown.'),
    recording_subject_email: zod
        .string()
        .nullable()
        .describe(
            'Email of the person in the recorded session (the subject being watched, not the user who triggered the observation), captured at scan time. Null when the session had no identified person.'
        ),
    previous_observation_id: zod
        .uuid()
        .nullable()
        .describe(
            'Id of the preceding sibling observation for the same scanner (prev\/next nav), honoring any list filters and ordering passed to retrieve; only set on retrieve, null at the start of the set.'
        ),
    next_observation_id: zod
        .uuid()
        .nullable()
        .describe(
            'Id of the following sibling observation for the same scanner (prev\/next nav), honoring any list filters and ordering passed to retrieve; only set on retrieve, null at the end of the set.'
        ),
    label: zod
        .union([ReplayObservationLabelApi, zod.null()])
        .describe("The team's shared label on this observation (correct\/incorrect + feedback), or null if unlabeled."),
    started_at: zod.iso.datetime({ offset: true }).nullish(),
    completed_at: zod.iso.datetime({ offset: true }).nullish(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type ReplayObservationApi = zod.input<typeof ReplayObservationApi>
export type ReplayObservationApiOutput = zod.output<typeof ReplayObservationApi>

export const PaginatedReplayObservationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ReplayObservationApi),
})

export type PaginatedReplayObservationListApi = zod.input<typeof PaginatedReplayObservationListApi>
export type PaginatedReplayObservationListApiOutput = zod.output<typeof PaginatedReplayObservationListApi>

export const CreateTaskFromObservationResponseApi = zod
    .object({
        task_id: zod
            .uuid()
            .describe(
                "ID of the PostHog Task holding this observation's finding, created now (201) or by an earlier call (200)."
            ),
    })
    .describe('The PostHog Task created from an observation.')

export type CreateTaskFromObservationResponseApi = zod.input<typeof CreateTaskFromObservationResponseApi>
export type CreateTaskFromObservationResponseApiOutput = zod.output<typeof CreateTaskFromObservationResponseApi>

export const RetryResponseApi = zod
    .object({
        workflow_id: zod
            .string()
            .describe(
                'Temporal workflow id for the re-run. The retried observation row is deleted; look up its replacement via GET \/vision\/scanners\/{id}\/observations\/?session_id=<session_id>.'
            ),
    })
    .describe('Async-accepted response for POST \/vision\/scanners\/{id}\/observations\/{id}\/retry\/.')

export type RetryResponseApi = zod.input<typeof RetryResponseApi>
export type RetryResponseApiOutput = zod.output<typeof RetryResponseApi>

export const VisionQuotaApi = zod.object({
    credit_limit: zod
        .number()
        .nullable()
        .describe(
            'Credits the org may spend per billing period (1 credit = $0.01). Null when billing has synced the product with no spend limit: uncapped.'
        ),
    credits_used: zod
        .number()
        .describe(
            'Credits spent this period: succeeded observations from the receipt ledger plus reserved in-flight observations.'
        ),
    remaining: zod.number().nullable().describe('`credit_limit - credits_used`, floored at 0. Null when uncapped.'),
    exhausted: zod
        .boolean()
        .describe(
            'True when `credits_used >= credit_limit`; further observations are skipped until next period. Always false when uncapped.'
        ),
    period_start: zod.iso.datetime({ offset: true }).describe('First moment of the current quota period (UTC).'),
    period_end: zod.iso
        .datetime({ offset: true })
        .describe("First moment of the next quota period (UTC); the current period's exclusive upper bound."),
    projected_monthly_credits: zod
        .number()
        .describe(
            "Credit-weighted sum of enabled scanners' projected observations\/month across the organization. Scanners without a computed estimate contribute 0."
        ),
})

export type VisionQuotaApi = zod.input<typeof VisionQuotaApi>
export type VisionQuotaApiOutput = zod.output<typeof VisionQuotaApi>

export const SamplingModeEnumApi = zod
    .enum(['focused', 'balanced', 'comprehensive'])
    .describe('\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive')

export type SamplingModeEnumApi = zod.input<typeof SamplingModeEnumApi>
export type SamplingModeEnumApiOutput = zod.output<typeof SamplingModeEnumApi>

export const ScannerProviderEnumApi = zod.enum(['google']).describe('\* `google` - Google')

export type ScannerProviderEnumApi = zod.input<typeof ScannerProviderEnumApi>
export type ScannerProviderEnumApiOutput = zod.output<typeof ScannerProviderEnumApi>

export const ScannerModelEnumApi = zod
    .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.6-flash'])
    .describe(
        '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.6-flash` - Gemini 3.6 Flash'
    )

export type ScannerModelEnumApi = zod.input<typeof ScannerModelEnumApi>
export type ScannerModelEnumApiOutput = zod.output<typeof ScannerModelEnumApi>

export const FeedbackThemeSessionApi = zod.object({
    observation_id: zod.string().describe('Observation whose feedback comment backs this theme.'),
    session_id: zod.string().describe('Session recording the feedback comment was about.'),
})

export type FeedbackThemeSessionApi = zod.input<typeof FeedbackThemeSessionApi>
export type FeedbackThemeSessionApiOutput = zod.output<typeof FeedbackThemeSessionApi>

export const FeedbackThemeApi = zod.object({
    theme: zod
        .string()
        .describe('Short failure mode in sentence case, for example \"Review page mistaken for confirmation\".'),
    count: zod.number().describe('How many feedback comments describe this failure mode.'),
    examples: zod.array(zod.string()).describe('Up to two short representative quotes from the feedback comments.'),
    sessions: zod
        .array(FeedbackThemeSessionApi)
        .describe(
            'The rated sessions whose feedback comments back this theme. Empty for summaries generated before session tracking.'
        ),
})

export type FeedbackThemeApi = zod.input<typeof FeedbackThemeApi>
export type FeedbackThemeApiOutput = zod.output<typeof FeedbackThemeApi>

export const FeedbackThemesApi = zod.object({
    themes: zod.array(FeedbackThemeApi).describe('Recurring failure modes, most frequent first.'),
    feedback_count: zod.number().describe('Number of thumbs-down feedback comments the summary was generated from.'),
    generated_at: zod.iso.datetime({ offset: true }).describe('When the summary was generated.'),
})

export type FeedbackThemesApi = zod.input<typeof FeedbackThemesApi>
export type FeedbackThemesApiOutput = zod.output<typeof FeedbackThemesApi>

export const replayScannerApiNameMax = 255

export const replayScannerApiDescriptionMax = 1000

export const replayScannerApiSamplingRateMin = 0
export const replayScannerApiSamplingRateMax = 1

export const ReplayScannerApi = zod
    .object({
        id: zod.uuid(),
        name: zod
            .string()
            .max(replayScannerApiNameMax)
            .describe('Human-readable scanner name. Unique within the team.'),
        description: zod
            .string()
            .max(replayScannerApiDescriptionMax)
            .optional()
            .describe('Free-form description shown in the scanner management UI.'),
        scanner_type: ScannerTypeEnumApi.describe(
            'What the scanner does: monitor, classifier, scorer, or summarizer.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
        ),
        scanner_config: zod
            .unknown()
            .describe(
                'Type-specific configuration. All scanner types require `prompt`; monitors add optional `allow_inconclusive`, classifiers add `tags`, scorers add `scale`, summarizers add optional `length`.'
            ),
        query: zod
            .unknown()
            .optional()
            .describe(
                'Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`\/`date_to` are stripped on save — the schedule controls time, not the user.'
            ),
        sampling_rate: zod
            .number()
            .min(replayScannerApiSamplingRateMin)
            .max(replayScannerApiSamplingRateMax)
            .optional()
            .describe(
                '0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling). Use exactly 0 to pause scanning; non-zero rates below 0.0001 (0.01%) are rejected as below the sampling precision.'
            ),
        sampling_mode: SamplingModeEnumApi.optional().describe(
            'Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).\n\n\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive'
        ),
        provider: ScannerProviderEnumApi.optional().describe(
            'LLM provider. v1 is Google-only.\n\n\* `google` - Google'
        ),
        model: ScannerModelEnumApi.describe(
            'Concrete model to use for this scanner.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.6-flash` - Gemini 3.6 Flash'
        ),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                "When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work."
            ),
        emits_signals: zod
            .boolean()
            .optional()
            .describe(
                'When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals.'
            ),
        scanner_version: zod
            .number()
            .describe('Increments on every config-changing save. Observations snapshot this value.'),
        estimated_monthly_observations: zod
            .number()
            .nullable()
            .describe('Latest projected observations\/month for this scanner. Null until first computed.'),
        credits_per_observation: zod
            .number()
            .describe('Credits one observation by this scanner costs (1 credit = $0.01), derived from `model`.'),
        estimated_monthly_credits: zod
            .number()
            .nullable()
            .describe(
                '`estimated_monthly_observations` priced at `credits_per_observation`. Null until the estimate is first computed.'
            ),
        credits_this_month: zod
            .number()
            .describe(
                "Credits this scanner's succeeded observations consumed in the current billing period (1 credit = $0.01). Matches the window of the org-wide quota meter."
            ),
        observations_this_month: zod
            .number()
            .describe('Succeeded observations this scanner produced in the current billing period.'),
        last_swept_at: zod.iso
            .datetime({ offset: true })
            .describe("Watermark for the scanner's last scheduled fire. Mirrors Temporal schedule state for recovery."),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created the scanner.'),
        updated_at: zod.iso.datetime({ offset: true }),
        feedback_themes: zod
            .union([FeedbackThemesApi, zod.null()])
            .describe(
                "AI summary of the team's written thumbs-down feedback into recurring failure modes. Refreshed with prompt recommendations; null until enough feedback accumulates."
            ),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('A Replay Vision scanner: its type, targeting query, and AI configuration.')

export type ReplayScannerApi = zod.input<typeof ReplayScannerApi>
export type ReplayScannerApiOutput = zod.output<typeof ReplayScannerApi>

export const PaginatedReplayScannerListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ReplayScannerApi),
})

export type PaginatedReplayScannerListApi = zod.input<typeof PaginatedReplayScannerListApi>
export type PaginatedReplayScannerListApiOutput = zod.output<typeof PaginatedReplayScannerListApi>

export const patchedReplayScannerApiNameMax = 255

export const patchedReplayScannerApiDescriptionMax = 1000

export const patchedReplayScannerApiSamplingRateMin = 0
export const patchedReplayScannerApiSamplingRateMax = 1

export const PatchedReplayScannerApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod
            .string()
            .max(patchedReplayScannerApiNameMax)
            .optional()
            .describe('Human-readable scanner name. Unique within the team.'),
        description: zod
            .string()
            .max(patchedReplayScannerApiDescriptionMax)
            .optional()
            .describe('Free-form description shown in the scanner management UI.'),
        scanner_type: ScannerTypeEnumApi.optional().describe(
            'What the scanner does: monitor, classifier, scorer, or summarizer.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
        ),
        scanner_config: zod
            .unknown()
            .optional()
            .describe(
                'Type-specific configuration. All scanner types require `prompt`; monitors add optional `allow_inconclusive`, classifiers add `tags`, scorers add `scale`, summarizers add optional `length`.'
            ),
        query: zod
            .unknown()
            .optional()
            .describe(
                'Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`\/`date_to` are stripped on save — the schedule controls time, not the user.'
            ),
        sampling_rate: zod
            .number()
            .min(patchedReplayScannerApiSamplingRateMin)
            .max(patchedReplayScannerApiSamplingRateMax)
            .optional()
            .describe(
                '0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling). Use exactly 0 to pause scanning; non-zero rates below 0.0001 (0.01%) are rejected as below the sampling precision.'
            ),
        sampling_mode: SamplingModeEnumApi.optional().describe(
            'Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).\n\n\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive'
        ),
        provider: ScannerProviderEnumApi.optional().describe(
            'LLM provider. v1 is Google-only.\n\n\* `google` - Google'
        ),
        model: ScannerModelEnumApi.optional().describe(
            'Concrete model to use for this scanner.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.6-flash` - Gemini 3.6 Flash'
        ),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                "When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work."
            ),
        emits_signals: zod
            .boolean()
            .optional()
            .describe(
                'When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals.'
            ),
        scanner_version: zod
            .number()
            .optional()
            .describe('Increments on every config-changing save. Observations snapshot this value.'),
        estimated_monthly_observations: zod
            .number()
            .nullish()
            .describe('Latest projected observations\/month for this scanner. Null until first computed.'),
        credits_per_observation: zod
            .number()
            .optional()
            .describe('Credits one observation by this scanner costs (1 credit = $0.01), derived from `model`.'),
        estimated_monthly_credits: zod
            .number()
            .nullish()
            .describe(
                '`estimated_monthly_observations` priced at `credits_per_observation`. Null until the estimate is first computed.'
            ),
        credits_this_month: zod
            .number()
            .optional()
            .describe(
                "Credits this scanner's succeeded observations consumed in the current billing period (1 credit = $0.01). Matches the window of the org-wide quota meter."
            ),
        observations_this_month: zod
            .number()
            .optional()
            .describe('Succeeded observations this scanner produced in the current billing period.'),
        last_swept_at: zod.iso
            .datetime({ offset: true })
            .optional()
            .describe("Watermark for the scanner's last scheduled fire. Mirrors Temporal schedule state for recovery."),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: zod.union([UserBasicApi, zod.null()]).optional().describe('User who created the scanner.'),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        feedback_themes: zod
            .union([FeedbackThemesApi, zod.null()])
            .optional()
            .describe(
                "AI summary of the team's written thumbs-down feedback into recurring failure modes. Refreshed with prompt recommendations; null until enough feedback accumulates."
            ),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
    })
    .describe('A Replay Vision scanner: its type, targeting query, and AI configuration.')

export type PatchedReplayScannerApi = zod.input<typeof PatchedReplayScannerApi>
export type PatchedReplayScannerApiOutput = zod.output<typeof PatchedReplayScannerApi>

export const affectedCohortRequestApiWindowDaysDefault = 30
export const affectedCohortRequestApiWindowDaysMax = 90

export const affectedCohortRequestApiTagMax = 100

export const AffectedCohortRequestApi = zod
    .object({
        window_days: zod
            .number()
            .min(1)
            .max(affectedCohortRequestApiWindowDaysMax)
            .default(affectedCohortRequestApiWindowDaysDefault)
            .describe('Trailing window of observations to count. Defaults to 30 days.'),
        tag: zod
            .string()
            .max(affectedCohortRequestApiTagMax)
            .nullish()
            .describe(
                'Classifier scanners only, required for them: count sessions carrying this tag (fixed or freeform). Not applicable to other scanner types.'
            ),
        min_score: zod
            .number()
            .nullish()
            .describe(
                'Scorer scanners only: count sessions scoring at or above this value. Scorers require `min_score` and\/or `max_score`. Not applicable to other scanner types.'
            ),
        max_score: zod
            .number()
            .nullish()
            .describe('Scorer scanners only: count sessions scoring at or below this value.'),
    })
    .describe('Body of POST \/vision\/scanners\/:id\/affected_cohort\/. Same qualifiers as the impact GET.')

export type AffectedCohortRequestApi = zod.input<typeof AffectedCohortRequestApi>
export type AffectedCohortRequestApiOutput = zod.output<typeof AffectedCohortRequestApi>

export const AffectedCohortResponseApi = zod
    .object({
        cohort_id: zod
            .number()
            .describe('ID of the created static cohort; usable anywhere cohorts are (funnels, surveys, experiments).'),
        name: zod
            .string()
            .describe("Generated cohort name, stamped with the creation date since the snapshot doesn't live-update."),
        users_in_cohort: zod
            .number()
            .describe(
                'Persons actually in the created cohort. Can be lower than `affected_users`: matched distinct IDs without a person profile are dropped, and merged persons deduplicate.'
            ),
        window_days: zod.number().describe('Trailing window the cohort was drawn from, in days.'),
    })
    .describe("The static cohort created from the scanner's affected users.")

export type AffectedCohortResponseApi = zod.input<typeof AffectedCohortResponseApi>
export type AffectedCohortResponseApiOutput = zod.output<typeof AffectedCohortResponseApi>

export const bulkObserveRequestApiSessionIdsItemMax = 128

export const bulkObserveRequestApiSessionIdsMax = 200

export const BulkObserveRequestApi = zod
    .object({
        session_ids: zod
            .array(zod.string().max(bulkObserveRequestApiSessionIdsItemMax))
            .max(bulkObserveRequestApiSessionIdsMax)
            .describe(
                'Session recording IDs to scan on demand, at most 200 per request. Scans start until the in-flight limit or monthly credit quota is reached; the rest are reported as skipped rather than failing the whole batch. Already-running sessions are a no-op.'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/{id}\/bulk_observe\/.')

export type BulkObserveRequestApi = zod.input<typeof BulkObserveRequestApi>
export type BulkObserveRequestApiOutput = zod.output<typeof BulkObserveRequestApi>

export const ScanOutcomeEnumApi = zod
    .enum(['started', 'already_running', 'skipped_limit', 'skipped_quota', 'failed'])
    .describe(
        '\* `started` - Started\n\* `already_running` - Already running\n\* `skipped_limit` - Skipped — in-flight limit reached\n\* `skipped_quota` - Skipped — monthly credit quota reached\n\* `failed` - Failed to start'
    )

export type ScanOutcomeEnumApi = zod.input<typeof ScanOutcomeEnumApi>
export type ScanOutcomeEnumApiOutput = zod.output<typeof ScanOutcomeEnumApi>

export const BulkObserveResultApi = zod
    .object({
        session_id: zod.string().describe('The session recording this outcome is for.'),
        scan_outcome: ScanOutcomeEnumApi.describe(
            "'started' — a scan workflow was kicked off; 'already_running' — a scan for this session is already in flight (no-op, not recharged); 'skipped_limit' — the in-flight cap was reached before this session; 'skipped_quota' — the monthly credit quota would be exceeded; 'failed' — the workflow failed to start.\n\n\* `started` - Started\n\* `already_running` - Already running\n\* `skipped_limit` - Skipped — in-flight limit reached\n\* `skipped_quota` - Skipped — monthly credit quota reached\n\* `failed` - Failed to start"
        ),
    })
    .describe('Per-session outcome of a bulk scan trigger.')

export type BulkObserveResultApi = zod.input<typeof BulkObserveResultApi>
export type BulkObserveResultApiOutput = zod.output<typeof BulkObserveResultApi>

export const BulkObserveResponseApi = zod
    .object({
        started: zod.number().describe('How many new scans were started.'),
        results: zod.array(BulkObserveResultApi).describe('Per-session outcomes, in request order (deduplicated).'),
    })
    .describe('Result of POST \/vision\/scanners\/{id}\/bulk_observe\/ — partial success by design.')

export type BulkObserveResponseApi = zod.input<typeof BulkObserveResponseApi>
export type BulkObserveResponseApiOutput = zod.output<typeof BulkObserveResponseApi>

export const ScannerImpactApi = zod
    .object({
        affected_sessions: zod
            .number()
            .describe(
                'Distinct sessions with an affected observation in the window. For monitors only verdict-yes observations count; for other scanner types every succeeded observation counts.'
            ),
        affected_users: zod
            .number()
            .describe(
                'Distinct users behind the affected sessions, by distinct ID. May include anonymous device IDs when the recorded sessions were not identified.'
            ),
        sessions_without_user: zod
            .number()
            .describe('Affected sessions whose recording carried no distinct ID at all.'),
        window_days: zod.number().describe('Trailing window the counts cover, in days.'),
    })
    .describe("Who this scanner's findings affected in the window; counted from observations, not estimated.")

export type ScannerImpactApi = zod.input<typeof ScannerImpactApi>
export type ScannerImpactApiOutput = zod.output<typeof ScannerImpactApi>

export const observeRequestApiSessionIdMax = 128

export const ObserveRequestApi = zod
    .object({
        session_id: zod
            .string()
            .max(observeRequestApiSessionIdMax)
            .describe('ID of the session recording to apply the scanner to.'),
    })
    .describe('Body of POST \/vision\/scanners\/{id}\/observe\/.')

export type ObserveRequestApi = zod.input<typeof ObserveRequestApi>
export type ObserveRequestApiOutput = zod.output<typeof ObserveRequestApi>

export const ObserveResponseApi = zod
    .object({
        workflow_id: zod
            .string()
            .describe(
                'Temporal workflow id for this scanner application. Look up the resulting ReplayObservation via GET \/vision\/scanners\/{id}\/observations\/?session_id=<session_id>.'
            ),
    })
    .describe('Async-accepted response for POST \/vision\/scanners\/{id}\/observe\/.')

export type ObserveResponseApi = zod.input<typeof ObserveResponseApi>
export type ObserveResponseApiOutput = zod.output<typeof ObserveResponseApi>

export const ObservationStatusCountsApi = zod.object({
    total: zod.number().describe('Total observations in the filtered set.'),
    succeeded: zod.number().describe('Observations with `status=succeeded`.'),
    failed: zod.number().describe('Observations with `status=failed`.'),
    ineligible: zod.number().describe('Observations with `status=ineligible`.'),
    in_flight: zod.number().describe('Observations not yet in a terminal status.'),
    success_rate: zod
        .number()
        .nullable()
        .describe(
            'Percentage of (succeeded + failed) observations that succeeded; ineligible rows are excluded. Null when no observations have completed.'
        ),
})

export type ObservationStatusCountsApi = zod.input<typeof ObservationStatusCountsApi>
export type ObservationStatusCountsApiOutput = zod.output<typeof ObservationStatusCountsApi>

export const CoverageStatsApi = zod.object({
    recent_sessions: zod.number().describe('Distinct sessions observed within the last `recent_days` days.'),
    total_sessions: zod.number().describe('Distinct sessions observed overall.'),
    recent_days: zod.number().describe('Window size in days used for `recent_sessions`.'),
})

export type CoverageStatsApi = zod.input<typeof CoverageStatsApi>
export type CoverageStatsApiOutput = zod.output<typeof CoverageStatsApi>

export const ObservationLabelDayCountApi = zod.object({
    date: zod.iso.date().describe('Day (UTC) the observed sessions were scanned.'),
    up: zod.number().describe('Observations scanned this day labeled correct (thumbs up).'),
    down: zod.number().describe('Observations scanned this day labeled incorrect (thumbs down).'),
})

export type ObservationLabelDayCountApi = zod.input<typeof ObservationLabelDayCountApi>
export type ObservationLabelDayCountApiOutput = zod.output<typeof ObservationLabelDayCountApi>

export const ObservationVersionMarkerApi = zod.object({
    date: zod.iso.date().describe('First day (UTC) this prompt version produced observations.'),
    version: zod.number().describe('The scanner (prompt) version number.'),
    prompt: zod.string().describe('The prompt text this version ran with, taken from the observation run snapshots.'),
    scanner_config: zod
        .unknown()
        .describe(
            'The full type-specific config this version ran with (prompt plus, depending on scanner type, allow_inconclusive, tags, scale, or length), taken from the observation run snapshots.'
        ),
    up: zod.number().describe("Thumbs-up ratings on this version's observations."),
    down: zod.number().describe("Thumbs-down ratings on this version's observations."),
    total: zod.number().describe('Succeeded (ratable) observations this version produced, rated or not.'),
})

export type ObservationVersionMarkerApi = zod.input<typeof ObservationVersionMarkerApi>
export type ObservationVersionMarkerApiOutput = zod.output<typeof ObservationVersionMarkerApi>

export const ObservationLabelStatsApi = zod.object({
    up_total: zod.number().describe('Observations in the filtered set labeled correct (thumbs up).'),
    down_total: zod.number().describe('Observations in the filtered set labeled incorrect (thumbs down).'),
    by_day: zod
        .array(ObservationLabelDayCountApi)
        .describe(
            'Daily label counts over the last `recent_days` days, bucketed by the day the session was scanned so the series tracks scanner quality over time. Days without labels are omitted.'
        ),
    by_rating_day: zod
        .array(ObservationLabelDayCountApi)
        .describe(
            "Daily label counts over the last `recent_days` days, bucketed by the day the rating was last set or changed: the team's rating activity. Days without rating changes are omitted."
        ),
    version_markers: zod
        .array(ObservationVersionMarkerApi)
        .describe(
            'Each scanner (prompt) version that produced observations (all-time), with its first day, prompt, and rating counts, for chart markers and the prompt version history.'
        ),
})

export type ObservationLabelStatsApi = zod.input<typeof ObservationLabelStatsApi>
export type ObservationLabelStatsApiOutput = zod.output<typeof ObservationLabelStatsApi>

export const MonitorStatsApi = zod.object({
    yes_total: zod.number().describe('Succeeded observations whose verdict was `yes`.'),
    no_total: zod.number().describe('Succeeded observations whose verdict was `no`.'),
    inconclusive_total: zod.number().describe('Succeeded observations whose verdict was `inconclusive`.'),
})

export type MonitorStatsApi = zod.input<typeof MonitorStatsApi>
export type MonitorStatsApiOutput = zod.output<typeof MonitorStatsApi>

export const TagCountApi = zod.object({
    tag: zod.string().describe('The tag value.'),
    count: zod.number().describe('Number of succeeded observations carrying this tag.'),
})

export type TagCountApi = zod.input<typeof TagCountApi>
export type TagCountApiOutput = zod.output<typeof TagCountApi>

export const ClassifierStatsApi = zod.object({
    fixed_ranked: zod.array(TagCountApi).describe('Top fixed-vocabulary tags by emission count.'),
    freeform_ranked: zod.array(TagCountApi).describe('Top freeform tags by emission count.'),
    total_with_tags: zod.number().describe('Succeeded observations that emitted at least one tag.'),
})

export type ClassifierStatsApi = zod.input<typeof ClassifierStatsApi>
export type ClassifierStatsApiOutput = zod.output<typeof ClassifierStatsApi>

export const ScorerSummaryApi = zod.object({
    min: zod.number().describe('Minimum observed score.'),
    p25: zod.number().describe('25th-percentile score.'),
    median: zod.number().describe('Median score.'),
    mean: zod.number().describe('Mean score.'),
    p75: zod.number().describe('75th-percentile score.'),
    max: zod.number().describe('Maximum observed score.'),
    count: zod.number().describe('Number of scored observations summarized.'),
})

export type ScorerSummaryApi = zod.input<typeof ScorerSummaryApi>
export type ScorerSummaryApiOutput = zod.output<typeof ScorerSummaryApi>

export const ScorerHistogramApi = zod.object({
    labels: zod
        .array(zod.string())
        .describe("Bucket labels (one per histogram bar) spanning the scanner's configured scale."),
    counts: zod.array(zod.number()).describe('Observation count per bucket; same length as `labels`.'),
})

export type ScorerHistogramApi = zod.input<typeof ScorerHistogramApi>
export type ScorerHistogramApiOutput = zod.output<typeof ScorerHistogramApi>

export const ScorerStatsApi = zod.object({
    summary: zod
        .union([ScorerSummaryApi, zod.null()])
        .describe('Score quantile summary; null when no observations have been scored.'),
    histogram: zod
        .union([ScorerHistogramApi, zod.null()])
        .describe('Score histogram; null when no observations have been scored.'),
})

export type ScorerStatsApi = zod.input<typeof ScorerStatsApi>
export type ScorerStatsApiOutput = zod.output<typeof ScorerStatsApi>

export const FacetCountApi = zod.object({
    term: zod.string().describe('The facet value as emitted by the summarizer (lowercased).'),
    count: zod.number().describe('Number of succeeded observations that emitted this value.'),
})

export type FacetCountApi = zod.input<typeof FacetCountApi>
export type FacetCountApiOutput = zod.output<typeof FacetCountApi>

export const SummarizerStatsApi = zod.object({
    friction_ranked: zod.array(FacetCountApi).describe('Top friction points by emission count.'),
    keyword_ranked: zod.array(FacetCountApi).describe('Top keywords by emission count.'),
    total_with_facets: zod
        .number()
        .describe('Succeeded observations that emitted at least one friction point or keyword.'),
    total_with_friction: zod.number().describe('Succeeded observations that reported at least one friction point.'),
})

export type SummarizerStatsApi = zod.input<typeof SummarizerStatsApi>
export type SummarizerStatsApiOutput = zod.output<typeof SummarizerStatsApi>

export const ObservationStatsApi = zod.object({
    status_counts: ObservationStatusCountsApi.describe('Counts of observations by terminal status.'),
    coverage: CoverageStatsApi.describe('Session-level scanner coverage.'),
    labels: ObservationLabelStatsApi.describe('Team label (thumbs up\/down) aggregates over the filtered set.'),
    available_tags: zod
        .array(zod.string())
        .describe('All distinct tags (fixed + freeform) emitted by succeeded observations in the filtered set.'),
    monitor: zod
        .union([MonitorStatsApi, zod.null()])
        .describe('Monitor-type aggregates; null when the scanner is not a monitor.'),
    classifier: zod
        .union([ClassifierStatsApi, zod.null()])
        .describe('Classifier-type aggregates; null when the scanner is not a classifier.'),
    scorer: zod
        .union([ScorerStatsApi, zod.null()])
        .describe('Scorer-type aggregates; null when the scanner is not a scorer.'),
    summarizer: zod
        .union([SummarizerStatsApi, zod.null()])
        .describe('Summarizer-type facet aggregates; null when the scanner is not a summarizer.'),
})

export type ObservationStatsApi = zod.input<typeof ObservationStatsApi>
export type ObservationStatsApiOutput = zod.output<typeof ObservationStatsApi>

export const ReplayScannerPromptSuggestionStatusEnumApi = zod
    .enum(['pending', 'applied', 'dismissed', 'superseded', 'no_change'])
    .describe(
        '\* `pending` - Pending\n\* `applied` - Applied\n\* `dismissed` - Dismissed\n\* `superseded` - Superseded\n\* `no_change` - No change'
    )

export type ReplayScannerPromptSuggestionStatusEnumApi = zod.input<typeof ReplayScannerPromptSuggestionStatusEnumApi>
export type ReplayScannerPromptSuggestionStatusEnumApiOutput = zod.output<
    typeof ReplayScannerPromptSuggestionStatusEnumApi
>

export const PromptEvaluationResultApi = zod.object({
    session_id: zod.string().describe('The rated session that was re-run with the suggested prompt.'),
    observation_id: zod.string().describe('The original rated observation the comparison is against.'),
    rated_correct: zod.boolean().describe("The team's rating of the original output (thumbs up = true)."),
    before: zod.string().nullable().describe("The original output's primary outcome."),
    after: zod
        .string()
        .nullable()
        .describe(
            "The suggested prompt's outcome for the same session. Null when the run errored or returned no discrete outcome (e.g. a classifier with no tags)."
        ),
    outcome: zod
        .string()
        .describe(
            'kept (up, unchanged), regressed (up, changed), fixed (down, changed), still_wrong (down, unchanged), error, or preview (scorer\/summarizer: raw before\/after, no classification).'
        ),
    error: zod.string().nullable().describe("Why this session's re-run failed, when it did."),
})

export type PromptEvaluationResultApi = zod.input<typeof PromptEvaluationResultApi>
export type PromptEvaluationResultApiOutput = zod.output<typeof PromptEvaluationResultApi>

export const PromptEvaluationSummaryApi = zod.object({
    kept: zod.number().describe('Thumbs-up sessions whose output is unchanged.'),
    regressed: zod.number().describe('Thumbs-up sessions whose output changed.'),
    fixed: zod.number().describe('Thumbs-down sessions whose output changed.'),
    still_wrong: zod.number().describe('Thumbs-down sessions whose output is unchanged.'),
    errors: zod.number().describe('Sessions whose re-run failed.'),
})

export type PromptEvaluationSummaryApi = zod.input<typeof PromptEvaluationSummaryApi>
export type PromptEvaluationSummaryApiOutput = zod.output<typeof PromptEvaluationSummaryApi>

export const PromptSuggestionEvaluationApi = zod.object({
    status: zod.string().describe('running, succeeded, or failed.'),
    started_at: zod.iso.datetime({ offset: true }).describe('When the evaluation started.'),
    finished_at: zod.iso.datetime({ offset: true }).nullable().describe('When the evaluation finished, if it has.'),
    total: zod.number().describe('How many rated sessions are being re-run.'),
    labels_fingerprint: zod.string().describe('The rated set the evaluation ran against.'),
    results: zod.array(PromptEvaluationResultApi).describe('Per-session outcomes, in completion order.'),
    summary: zod
        .union([PromptEvaluationSummaryApi, zod.null()])
        .describe('Outcome counts. Null while the evaluation is running.'),
})

export type PromptSuggestionEvaluationApi = zod.input<typeof PromptSuggestionEvaluationApi>
export type PromptSuggestionEvaluationApiOutput = zod.output<typeof PromptSuggestionEvaluationApi>

export const ReplayScannerPromptSuggestionApi = zod.object({
    id: zod.uuid(),
    status: ReplayScannerPromptSuggestionStatusEnumApi.describe(
        'pending (current), applied, dismissed, or superseded by a newer suggestion.\n\n\* `pending` - Pending\n\* `applied` - Applied\n\* `dismissed` - Dismissed\n\* `superseded` - Superseded\n\* `no_change` - No change'
    ),
    suggested_prompt: zod.string().describe('The full rewritten prompt, ready to apply to the scanner.'),
    base_prompt: zod.string().describe('The scanner prompt this suggestion was generated against, for diffing.'),
    base_config: zod.unknown().describe('The scanner config this suggestion was generated against.'),
    suggested_config: zod.unknown().describe('The full proposed scanner config, ready to apply.'),
    changes: zod.unknown().describe('Typed per-field diff entries driving the change cards.'),
    rationale: zod.string().describe('What the rewrite changed and why, grounded in the ratings.'),
    based_on_up: zod.number().describe('Thumbs-up ratings the suggestion was based on.'),
    based_on_down: zod.number().describe('Thumbs-down ratings the suggestion was based on.'),
    scanner_version: zod.number().describe('The scanner version whose prompt this suggestion was generated against.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod
        .union([UserBasicApi, zod.null()])
        .describe('User who requested this suggestion; null for automatic refreshes.'),
    applied_at: zod.iso.datetime({ offset: true }).nullable(),
    applied_by: zod
        .union([UserBasicApi, zod.null()])
        .describe('User who applied this suggestion to the scanner; null unless applied.'),
    evaluation: zod
        .union([PromptSuggestionEvaluationApi, zod.null()])
        .describe('Test-before-apply results: the suggested prompt re-run against rated sessions.'),
})

export type ReplayScannerPromptSuggestionApi = zod.input<typeof ReplayScannerPromptSuggestionApi>
export type ReplayScannerPromptSuggestionApiOutput = zod.output<typeof ReplayScannerPromptSuggestionApi>

export const PaginatedReplayScannerPromptSuggestionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ReplayScannerPromptSuggestionApi),
})

export type PaginatedReplayScannerPromptSuggestionListApi = zod.input<
    typeof PaginatedReplayScannerPromptSuggestionListApi
>
export type PaginatedReplayScannerPromptSuggestionListApiOutput = zod.output<
    typeof PaginatedReplayScannerPromptSuggestionListApi
>

export const ApplyPromptSuggestionRequestApi = zod.object({
    config: zod
        .unknown()
        .optional()
        .describe(
            "The edited config to apply, assembled from the recommendation's approved fields. Omit to apply the full suggested config unchanged."
        ),
})

export type ApplyPromptSuggestionRequestApi = zod.input<typeof ApplyPromptSuggestionRequestApi>
export type ApplyPromptSuggestionRequestApiOutput = zod.output<typeof ApplyPromptSuggestionRequestApi>

export const evaluatePromptSuggestionRequestApiSessionLimitDefault = 10
export const evaluatePromptSuggestionRequestApiSessionLimitMax = 100

export const EvaluatePromptSuggestionRequestApi = zod.object({
    session_limit: zod
        .number()
        .min(1)
        .max(evaluatePromptSuggestionRequestApiSessionLimitMax)
        .default(evaluatePromptSuggestionRequestApiSessionLimitDefault)
        .describe(
            'How many rated sessions to re-run, thumbs-down prioritized. Each successful re-run charges credits like a normal observation of the same model. Defaults to 10. The maximum is `evaluation_session_cap`.'
        ),
    config: zod
        .unknown()
        .optional()
        .describe(
            "The edited config to test, assembled from the recommendation's approved fields. Omit to test the full suggested config."
        ),
})

export type EvaluatePromptSuggestionRequestApi = zod.input<typeof EvaluatePromptSuggestionRequestApi>
export type EvaluatePromptSuggestionRequestApiOutput = zod.output<typeof EvaluatePromptSuggestionRequestApi>

export const CurrentPromptSuggestionApi = zod.object({
    suggestion: zod
        .union([ReplayScannerPromptSuggestionApi, zod.null()])
        .describe('The newest suggestion for this scanner, or null when none has been generated yet.'),
    stale: zod.boolean().describe("True when the team's ratings changed since the newest suggestion was generated."),
    rated_count: zod
        .number()
        .describe('Number of rated (thumbs up or down) succeeded observations available to generate from.'),
    evaluation_session_cap: zod
        .number()
        .describe(
            'Maximum rated sessions one suggestion test re-runs. Each successful re-run charges credits like a normal observation of the same model.'
        ),
})

export type CurrentPromptSuggestionApi = zod.input<typeof CurrentPromptSuggestionApi>
export type CurrentPromptSuggestionApiOutput = zod.output<typeof CurrentPromptSuggestionApi>

export const ScannerCreatorsResponseApi = zod
    .object({
        creators: zod
            .array(UserBasicApi)
            .describe(
                'Users who created at least one scanner on this team. Returned regardless of pagination state so the dropdown stays stable across pages.'
            ),
    })
    .describe('Distinct creators across all scanners on the team — feeds the `Created by` filter dropdown.')

export type ScannerCreatorsResponseApi = zod.input<typeof ScannerCreatorsResponseApi>
export type ScannerCreatorsResponseApiOutput = zod.output<typeof ScannerCreatorsResponseApi>

export const estimateRequestApiSamplingRateDefault = 1
export const estimateRequestApiSamplingRateMin = 0
export const estimateRequestApiSamplingRateMax = 1

export const estimateRequestApiSamplingModeDefault = `comprehensive`
export const estimateRequestApiModelDefault = `gemini-3-flash-preview`

export const EstimateRequestApi = zod
    .object({
        query: zod
            .unknown()
            .optional()
            .describe(
                'Proposed `RecordingsQuery` for the candidate filter. `date_from`\/`date_to` are ignored — the estimate always uses a fixed 30-day lookback. Omit to estimate against all recordings.'
            ),
        sampling_rate: zod
            .number()
            .min(estimateRequestApiSamplingRateMin)
            .max(estimateRequestApiSamplingRateMax)
            .default(estimateRequestApiSamplingRateDefault)
            .describe('0..1 downsample applied to matched sessions. Defaults to 1.0 (no downsampling).'),
        sampling_mode: SamplingModeEnumApi.default(estimateRequestApiSamplingModeDefault).describe(
            "Quality pre-filter applied to the matched-session count, mirroring the sweep's candidate query. Defaults to comprehensive (no filter).\n\n\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive"
        ),
        scanner_id: zod
            .uuid()
            .nullish()
            .describe(
                "The scanner being edited, excluded from `other_enabled_scanners_monthly_credits` so its stored estimate isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner."
            ),
        model: ScannerModelEnumApi.default(estimateRequestApiModelDefault).describe(
            'Proposed model; determines `credits_per_observation` in the response.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.6-flash` - Gemini 3.6 Flash'
        ),
    })
    .describe('Body of POST \/vision\/scanners\/estimate\/ — a proposed, unsaved scanner config.')

export type EstimateRequestApi = zod.input<typeof EstimateRequestApi>
export type EstimateRequestApiOutput = zod.output<typeof EstimateRequestApi>

export const EstimateResponseApi = zod
    .object({
        matched_sessions_in_window: zod
            .number()
            .describe(
                'Distinct sessions matching the query within the 30-day lookback, after the sampling_mode quality filter but before random sampling.'
            ),
        window_days: zod
            .number()
            .describe(
                'Lookback window the estimate is based on. Normally 30; smaller when the team has fewer days of recordings.'
            ),
        estimated_observations_per_month: zod
            .number()
            .describe(
                'Projected monthly observations: quality-filtered matched sessions scaled to 30 days, times sampling_rate.'
            ),
        credits_per_observation: zod
            .number()
            .describe('Credits one observation costs at the proposed `model` (1 credit = $0.01).'),
        estimated_credits_per_month: zod
            .number()
            .describe('`estimated_observations_per_month` priced at `credits_per_observation`.'),
        other_enabled_scanners_monthly_credits: zod
            .number()
            .describe(
                "Credit-weighted projected monthly spend of the org's other enabled scanners (excluding `scanner_id`), from their cached estimates. Read from the same snapshot as this estimate so the forecast can't double-count the edited scanner."
            ),
        sampling_rate: zod.number().describe('Sampling rate applied to the projection. Echoed from the request.'),
    })
    .describe('Forward-looking volume and credit-cost estimate for a proposed scanner.')

export type EstimateResponseApi = zod.input<typeof EstimateResponseApi>
export type EstimateResponseApiOutput = zod.output<typeof EstimateResponseApi>

export const ScannerTypeStatsApi = zod
    .object({
        enabled: zod.number().describe('Number of enabled scanners of this type.'),
        total: zod.number().describe('Number of scanners of this type (enabled + disabled).'),
    })
    .describe('Per-scanner-type count of enabled vs total scanners.')

export type ScannerTypeStatsApi = zod.input<typeof ScannerTypeStatsApi>
export type ScannerTypeStatsApiOutput = zod.output<typeof ScannerTypeStatsApi>

export const ScannerStatsByTypeApi = zod
    .object({
        monitor: ScannerTypeStatsApi,
        classifier: ScannerTypeStatsApi,
        scorer: ScannerTypeStatsApi,
        summarizer: ScannerTypeStatsApi,
    })
    .describe(
        'One `ScannerTypeStats` per scanner type — explicit fields give callers a typed shape, not `Record<string, …>`.'
    )

export type ScannerStatsByTypeApi = zod.input<typeof ScannerStatsByTypeApi>
export type ScannerStatsByTypeApiOutput = zod.output<typeof ScannerStatsByTypeApi>

export const ScannerStatsResponseApi = zod
    .object({
        total: zod.number().describe('Total scanners on the team.'),
        enabled: zod.number().describe('Number of enabled scanners on the team.'),
        by_type: ScannerStatsByTypeApi.describe(
            'Per-scanner-type breakdown (monitor \/ classifier \/ scorer \/ summarizer).'
        ),
    })
    .describe('Team-wide scanner counts independent of any list-filter state.')

export type ScannerStatsResponseApi = zod.input<typeof ScannerStatsResponseApi>
export type ScannerStatsResponseApiOutput = zod.output<typeof ScannerStatsResponseApi>

export const suggestTagsRequestApiPromptMax = 10000

export const suggestTagsRequestApiTagsItemMax = 200

export const suggestTagsRequestApiTagsMax = 200

export const suggestTagsRequestApiMultiLabelDefault = true
export const suggestTagsRequestApiAllowFreeformTagsDefault = false

export const SuggestTagsRequestApi = zod
    .object({
        prompt: zod
            .string()
            .max(suggestTagsRequestApiPromptMax)
            .describe("The classifier's instruction prompt — the single dimension to categorize sessions by."),
        tags: zod
            .array(zod.string().max(suggestTagsRequestApiTagsItemMax))
            .max(suggestTagsRequestApiTagsMax)
            .optional()
            .describe('The current tag vocabulary, so suggestions never duplicate a tag the user already has.'),
        multi_label: zod
            .boolean()
            .default(suggestTagsRequestApiMultiLabelDefault)
            .describe('Whether the classifier assigns multiple tags per session.'),
        allow_freeform_tags: zod
            .boolean()
            .default(suggestTagsRequestApiAllowFreeformTagsDefault)
            .describe('Whether the classifier may emit tags outside the fixed vocabulary.'),
        scanner_id: zod
            .uuid()
            .nullish()
            .describe(
                'Existing scanner to ground suggestions in its own observations (the tags and reasoning it has already produced on real recordings). Omit for an unsaved scanner.'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/suggest_tags\/ — the classifier config currently being edited.')

export type SuggestTagsRequestApi = zod.input<typeof SuggestTagsRequestApi>
export type SuggestTagsRequestApiOutput = zod.output<typeof SuggestTagsRequestApi>

export const TagSuggestionSourceEnumApi = zod
    .enum(['observed', 'product', 'prompt'])
    .describe('\* `observed` - observed\n\* `product` - product\n\* `prompt` - prompt')

export type TagSuggestionSourceEnumApi = zod.input<typeof TagSuggestionSourceEnumApi>
export type TagSuggestionSourceEnumApiOutput = zod.output<typeof TagSuggestionSourceEnumApi>

export const TagSuggestionApi = zod
    .object({
        tag: zod.string().describe('Suggested tag to add to the vocabulary, normalized to lowercase.'),
        rationale: zod.string().describe('One sentence explaining the specific evidence this tag is grounded in.'),
        source: TagSuggestionSourceEnumApi.describe(
            "Primary grounding: observed=a category this scanner already emitted on recordings; product=the org's events\/screens; prompt=the scanner's stated goal.\n\n\* `observed` - observed\n\* `product` - product\n\* `prompt` - prompt"
        ),
    })
    .describe('One grounded tag suggestion.')

export type TagSuggestionApi = zod.input<typeof TagSuggestionApi>
export type TagSuggestionApiOutput = zod.output<typeof TagSuggestionApi>

export const SuggestTagsResponseApi = zod
    .object({
        suggestions: zod
            .array(TagSuggestionApi)
            .describe('Suggested tags to add, most relevant first. May be empty when the evidence is too thin.'),
    })
    .describe('Grounded tag suggestions for the classifier config editor.')

export type SuggestTagsResponseApi = zod.input<typeof SuggestTagsResponseApi>
export type SuggestTagsResponseApiOutput = zod.output<typeof SuggestTagsResponseApi>
