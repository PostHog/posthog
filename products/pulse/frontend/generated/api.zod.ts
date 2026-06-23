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
 * Kick off a one-off Pulse scan for this team now, without waiting for the schedule.
 *
 * Staff-only for now (404 hides it from non-staff); the gate can be relaxed to expose it to users later.
 *
 * An optional body of tuning knobs (PulseScanConfig) overrides the heuristics for this run only —
 * nothing is persisted. The override is staff-gated by the same 404 as the trigger itself. With no
 * body, the run resolves its detection thresholds from the team's PulseSubscription, as a scheduled
 * run would.
 */
export const pulseDigestsTriggerScanCreateBodyMaxCandidatesMax = 1000

export const pulseDigestsTriggerScanCreateBodyRecentDaysMax = 365

export const pulseDigestsTriggerScanCreateBodyMinViewersForRecentInsightMax = 100

export const pulseDigestsTriggerScanCreateBodyDashboardTileLimitMin = 0
export const pulseDigestsTriggerScanCreateBodyDashboardTileLimitMax = 200

export const pulseDigestsTriggerScanCreateBodyRecentInsightLimitMin = 0
export const pulseDigestsTriggerScanCreateBodyRecentInsightLimitMax = 500

export const pulseDigestsTriggerScanCreateBodySavedInsightLimitMin = 0
export const pulseDigestsTriggerScanCreateBodySavedInsightLimitMax = 200

export const pulseDigestsTriggerScanCreateBodyTopEventLimitMin = 0
export const pulseDigestsTriggerScanCreateBodyTopEventLimitMax = 500

export const pulseDigestsTriggerScanCreateBodyMinBaselineValueMin = 0
export const pulseDigestsTriggerScanCreateBodyMinBaselineValueMax = 1000000

export const pulseDigestsTriggerScanCreateBodyMinChangePctMin = 0.01
export const pulseDigestsTriggerScanCreateBodyMinChangePctMax = 10

export const pulseDigestsTriggerScanCreateBodyRobustZThresholdMin = 0.1
export const pulseDigestsTriggerScanCreateBodyRobustZThresholdMax = 10

export const pulseDigestsTriggerScanCreateBodyBaselineWeeksMin = 3
export const pulseDigestsTriggerScanCreateBodyBaselineWeeksMax = 12

export const pulseDigestsTriggerScanCreateBodyMaxFindingsMax = 50

export const PulseDigestsTriggerScanCreateBody = /* @__PURE__ */ zod
    .object({
        max_candidates: zod
            .number()
            .min(1)
            .max(pulseDigestsTriggerScanCreateBodyMaxCandidatesMax)
            .optional()
            .describe('Cap on total metrics scanned per run.'),
        recent_days: zod
            .number()
            .min(1)
            .max(pulseDigestsTriggerScanCreateBodyRecentDaysMax)
            .optional()
            .describe('Lookback window for recently-accessed dashboards and recently-viewed insights.'),
        min_viewers_for_recent_insight: zod
            .number()
            .min(1)
            .max(pulseDigestsTriggerScanCreateBodyMinViewersForRecentInsightMax)
            .optional()
            .describe('Minimum distinct viewers for the recently-viewed-insights source to include an insight.'),
        dashboard_tile_limit: zod
            .number()
            .min(pulseDigestsTriggerScanCreateBodyDashboardTileLimitMin)
            .max(pulseDigestsTriggerScanCreateBodyDashboardTileLimitMax)
            .optional()
            .describe('Max insights from pinned\/recent dashboards (0 = off).'),
        recent_insight_limit: zod
            .number()
            .min(pulseDigestsTriggerScanCreateBodyRecentInsightLimitMin)
            .max(pulseDigestsTriggerScanCreateBodyRecentInsightLimitMax)
            .optional()
            .describe('Max recently-viewed insights (0 = off).'),
        saved_insight_limit: zod
            .number()
            .min(pulseDigestsTriggerScanCreateBodySavedInsightLimitMin)
            .max(pulseDigestsTriggerScanCreateBodySavedInsightLimitMax)
            .optional()
            .describe('Max recently-edited saved Trends insights (0 = off).'),
        top_event_limit: zod
            .number()
            .min(pulseDigestsTriggerScanCreateBodyTopEventLimitMin)
            .max(pulseDigestsTriggerScanCreateBodyTopEventLimitMax)
            .optional()
            .describe('Max highest-volume events (0 = off).'),
        min_baseline_value: zod
            .number()
            .min(pulseDigestsTriggerScanCreateBodyMinBaselineValueMin)
            .max(pulseDigestsTriggerScanCreateBodyMinBaselineValueMax)
            .optional()
            .describe('Volume floor: skip metrics whose baseline median is below this (the top noise lever).'),
        min_change_pct: zod
            .number()
            .min(pulseDigestsTriggerScanCreateBodyMinChangePctMin)
            .max(pulseDigestsTriggerScanCreateBodyMinChangePctMax)
            .optional()
            .describe('Primary gate: minimum absolute fractional change to flag (0.25 = 25%).'),
        robust_z_threshold: zod
            .number()
            .min(pulseDigestsTriggerScanCreateBodyRobustZThresholdMin)
            .max(pulseDigestsTriggerScanCreateBodyRobustZThresholdMax)
            .optional()
            .describe('Secondary informational threshold for the robust z-score. Never a sole trigger.'),
        baseline_weeks: zod
            .number()
            .min(pulseDigestsTriggerScanCreateBodyBaselineWeeksMin)
            .max(pulseDigestsTriggerScanCreateBodyBaselineWeeksMax)
            .optional()
            .describe('Completed weeks used to compute the baseline median.'),
        max_findings: zod
            .number()
            .min(1)
            .max(pulseDigestsTriggerScanCreateBodyMaxFindingsMax)
            .optional()
            .describe('Maximum findings surfaced per digest.'),
    })
    .describe(
        'Per-run scan tuning knobs for a manual staff trigger.\n\nEvery field is optional; omitted knobs fall back to the built-in defaults (the production\nconstants), so a partial override is \"defaults plus the knobs you set\". Nothing is persisted —\nthe resolved config rides along with the one-off scan that started it.'
    )

export const pulseSubscriptionsCreateBodyMinChangePctMin = 0
export const pulseSubscriptionsCreateBodyMinChangePctMax = 1

export const pulseSubscriptionsCreateBodyBaselineWeeksMin = 3
export const pulseSubscriptionsCreateBodyBaselineWeeksMax = 52

export const pulseSubscriptionsCreateBodyMaxFindingsMax = 50

export const pulseSubscriptionsCreateBodyRobustZThresholdMin = 0.1
export const pulseSubscriptionsCreateBodyRobustZThresholdMax = 10

export const PulseSubscriptionsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Whether Pulse runs scans for this team.'),
    frequency: zod
        .enum(['weekly', 'daily'])
        .describe('\* `weekly` - Weekly\n\* `daily` - Daily')
        .optional()
        .describe('Scan cadence (weekly or daily).\n\n\* `weekly` - Weekly\n\* `daily` - Daily'),
    detection_mode: zod
        .enum(['change_v1', 'discovery'])
        .describe('\* `change_v1` - Change V1\n\* `discovery` - Discovery')
        .optional()
        .describe(
            "Detection algorithm. Only 'change_v1' is available in v1.\n\n\* `change_v1` - Change V1\n\* `discovery` - Discovery"
        ),
    sensitivity: zod
        .enum(['conservative', 'balanced', 'sensitive', 'custom'])
        .describe(
            '\* `conservative` - Conservative\n\* `balanced` - Balanced\n\* `sensitive` - Sensitive\n\* `custom` - Custom'
        )
        .optional()
        .describe(
            "Preset that derives thresholds, or 'custom' to use the raw knobs. Gates only the deterministic metric scan — anomalies surfaced by the AI scout bypass these thresholds.\n\n\* `conservative` - Conservative\n\* `balanced` - Balanced\n\* `sensitive` - Sensitive\n\* `custom` - Custom"
        ),
    min_change_pct: zod
        .number()
        .min(pulseSubscriptionsCreateBodyMinChangePctMin)
        .max(pulseSubscriptionsCreateBodyMinChangePctMax)
        .optional()
        .describe('Primary gate: minimum absolute fractional change to flag (0.0-1.0).'),
    baseline_weeks: zod
        .number()
        .min(pulseSubscriptionsCreateBodyBaselineWeeksMin)
        .max(pulseSubscriptionsCreateBodyBaselineWeeksMax)
        .optional()
        .describe('Number of completed weeks used to compute the baseline median.'),
    max_findings: zod
        .number()
        .min(1)
        .max(pulseSubscriptionsCreateBodyMaxFindingsMax)
        .optional()
        .describe('Maximum findings surfaced per digest.'),
    robust_z_threshold: zod
        .number()
        .min(pulseSubscriptionsCreateBodyRobustZThresholdMin)
        .max(pulseSubscriptionsCreateBodyRobustZThresholdMax)
        .optional()
        .describe('Secondary informational threshold for the robust z-score. Never a sole trigger.'),
})

export const pulseSubscriptionsUpdateBodyMinChangePctMin = 0
export const pulseSubscriptionsUpdateBodyMinChangePctMax = 1

export const pulseSubscriptionsUpdateBodyBaselineWeeksMin = 3
export const pulseSubscriptionsUpdateBodyBaselineWeeksMax = 52

export const pulseSubscriptionsUpdateBodyMaxFindingsMax = 50

export const pulseSubscriptionsUpdateBodyRobustZThresholdMin = 0.1
export const pulseSubscriptionsUpdateBodyRobustZThresholdMax = 10

export const PulseSubscriptionsUpdateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Whether Pulse runs scans for this team.'),
    frequency: zod
        .enum(['weekly', 'daily'])
        .describe('\* `weekly` - Weekly\n\* `daily` - Daily')
        .optional()
        .describe('Scan cadence (weekly or daily).\n\n\* `weekly` - Weekly\n\* `daily` - Daily'),
    detection_mode: zod
        .enum(['change_v1', 'discovery'])
        .describe('\* `change_v1` - Change V1\n\* `discovery` - Discovery')
        .optional()
        .describe(
            "Detection algorithm. Only 'change_v1' is available in v1.\n\n\* `change_v1` - Change V1\n\* `discovery` - Discovery"
        ),
    sensitivity: zod
        .enum(['conservative', 'balanced', 'sensitive', 'custom'])
        .describe(
            '\* `conservative` - Conservative\n\* `balanced` - Balanced\n\* `sensitive` - Sensitive\n\* `custom` - Custom'
        )
        .optional()
        .describe(
            "Preset that derives thresholds, or 'custom' to use the raw knobs. Gates only the deterministic metric scan — anomalies surfaced by the AI scout bypass these thresholds.\n\n\* `conservative` - Conservative\n\* `balanced` - Balanced\n\* `sensitive` - Sensitive\n\* `custom` - Custom"
        ),
    min_change_pct: zod
        .number()
        .min(pulseSubscriptionsUpdateBodyMinChangePctMin)
        .max(pulseSubscriptionsUpdateBodyMinChangePctMax)
        .optional()
        .describe('Primary gate: minimum absolute fractional change to flag (0.0-1.0).'),
    baseline_weeks: zod
        .number()
        .min(pulseSubscriptionsUpdateBodyBaselineWeeksMin)
        .max(pulseSubscriptionsUpdateBodyBaselineWeeksMax)
        .optional()
        .describe('Number of completed weeks used to compute the baseline median.'),
    max_findings: zod
        .number()
        .min(1)
        .max(pulseSubscriptionsUpdateBodyMaxFindingsMax)
        .optional()
        .describe('Maximum findings surfaced per digest.'),
    robust_z_threshold: zod
        .number()
        .min(pulseSubscriptionsUpdateBodyRobustZThresholdMin)
        .max(pulseSubscriptionsUpdateBodyRobustZThresholdMax)
        .optional()
        .describe('Secondary informational threshold for the robust z-score. Never a sole trigger.'),
})

export const pulseSubscriptionsPartialUpdateBodyMinChangePctMin = 0
export const pulseSubscriptionsPartialUpdateBodyMinChangePctMax = 1

export const pulseSubscriptionsPartialUpdateBodyBaselineWeeksMin = 3
export const pulseSubscriptionsPartialUpdateBodyBaselineWeeksMax = 52

export const pulseSubscriptionsPartialUpdateBodyMaxFindingsMax = 50

export const pulseSubscriptionsPartialUpdateBodyRobustZThresholdMin = 0.1
export const pulseSubscriptionsPartialUpdateBodyRobustZThresholdMax = 10

export const PulseSubscriptionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Whether Pulse runs scans for this team.'),
    frequency: zod
        .enum(['weekly', 'daily'])
        .describe('\* `weekly` - Weekly\n\* `daily` - Daily')
        .optional()
        .describe('Scan cadence (weekly or daily).\n\n\* `weekly` - Weekly\n\* `daily` - Daily'),
    detection_mode: zod
        .enum(['change_v1', 'discovery'])
        .describe('\* `change_v1` - Change V1\n\* `discovery` - Discovery')
        .optional()
        .describe(
            "Detection algorithm. Only 'change_v1' is available in v1.\n\n\* `change_v1` - Change V1\n\* `discovery` - Discovery"
        ),
    sensitivity: zod
        .enum(['conservative', 'balanced', 'sensitive', 'custom'])
        .describe(
            '\* `conservative` - Conservative\n\* `balanced` - Balanced\n\* `sensitive` - Sensitive\n\* `custom` - Custom'
        )
        .optional()
        .describe(
            "Preset that derives thresholds, or 'custom' to use the raw knobs. Gates only the deterministic metric scan — anomalies surfaced by the AI scout bypass these thresholds.\n\n\* `conservative` - Conservative\n\* `balanced` - Balanced\n\* `sensitive` - Sensitive\n\* `custom` - Custom"
        ),
    min_change_pct: zod
        .number()
        .min(pulseSubscriptionsPartialUpdateBodyMinChangePctMin)
        .max(pulseSubscriptionsPartialUpdateBodyMinChangePctMax)
        .optional()
        .describe('Primary gate: minimum absolute fractional change to flag (0.0-1.0).'),
    baseline_weeks: zod
        .number()
        .min(pulseSubscriptionsPartialUpdateBodyBaselineWeeksMin)
        .max(pulseSubscriptionsPartialUpdateBodyBaselineWeeksMax)
        .optional()
        .describe('Number of completed weeks used to compute the baseline median.'),
    max_findings: zod
        .number()
        .min(1)
        .max(pulseSubscriptionsPartialUpdateBodyMaxFindingsMax)
        .optional()
        .describe('Maximum findings surfaced per digest.'),
    robust_z_threshold: zod
        .number()
        .min(pulseSubscriptionsPartialUpdateBodyRobustZThresholdMin)
        .max(pulseSubscriptionsPartialUpdateBodyRobustZThresholdMax)
        .optional()
        .describe('Secondary informational threshold for the robust z-score. Never a sole trigger.'),
})
