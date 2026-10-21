import { dayjs } from 'lib/dayjs'
import posthog from 'lib/posthog-typed'
import type { ExperimentWarning, ExperimentWarningKey } from 'scenes/experiments/experimentLogic'
import { isLegacyExperiment } from 'scenes/experiments/utils'

import type { ExperimentExposureCriteria, ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { EXPERIMENT_VARIANT_MULTIPLE } from '../constants'
import { getExperimentStatus } from '../experimentStatus'
import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../generated/api.schemas'
import { getTotalExposures, hasSampleRatioMismatch } from './exposureHealth'
import { type HealthPanelCheck, countHealthChecks } from './healthPanelChecks'

// pinned: `finding_code` property values. Insights group and filter on them, so a rename breaks those insights.
export type ExperimentHealthFindingCode =
    | 'flag_off_while_running'
    | 'variant_shipped_while_running'
    | 'flag_live_after_end'
    | 'flag_live_before_launch'
    | 'bias_risk_multiple_excluded'
    | 'multiple_variants_share'
    | 'srm'
    | 'zero_exposures'
    | 'no_metric'
    | 'metric_event_not_ingested'
    | 'exposure_criteria_cannot_match'
    | 'forced_variant_release_condition'
    | 'flag_variants_mismatch'
    | 'split_changed_mid_run'
    | 'bucketing_changed_mid_run'
    | 'release_conditions_changed_mid_run'
    | 'new_flag_no_traffic'

export interface ExperimentHealthFinding {
    code: ExperimentHealthFindingCode
    /** The sub-case of the code, for example the warning key. It must not hold customer text. */
    variant?: string
    /** Set for a server finding. The separate warnings have none. */
    severity?: ExperimentHealthFindingApi['severity']
    reason?: string
}

// pinned: `open_kind` property values, for the same reason as the codes above.
export type ExperimentHealthFindingOpenKind = 'evidence' | 'docs' | 'why'

// pinned: `action_kind` property values, for the same reason as the codes above.
export type ExperimentHealthFindingActionKind =
    | 'adjust_distribution'
    | 'use_first_seen_variant'
    | 'open_feature_flag'
    | 'open_feature_flag_history'
    | 'edit_exposure_criteria'
    | 'edit_release_conditions'
    | 'add_primary_metric'
    | 'add_secondary_metric'

const EXPERIMENT_WARNING_FINDING_CODES: Record<ExperimentWarningKey, ExperimentHealthFindingCode> = {
    running_but_flag_disabled: 'flag_off_while_running',
    running_but_no_rollout: 'flag_off_while_running',
    running_but_single_variant_shipped: 'variant_shipped_while_running',
    ended_but_multiple_variants_rolled_out: 'flag_live_after_end',
    not_started_but_multiple_variants_rolled_out: 'flag_live_before_launch',
}

export const FLAG_STATE_FINDING_CODES: ReadonlySet<ExperimentHealthFindingCode> = new Set(
    Object.values(EXPERIMENT_WARNING_FINDING_CODES)
)

// pinned: `opened_from` property values of `experiment health checks opened`.
export type ExperimentHealthChecksOpenedFrom = 'meta_bar' | 'panel'

// pinned: `health_ui` property values. Insights compare the server's findings with the separate warnings on them.
// 'panel' means the page shows the server's findings: in the health panel when one is an issue, otherwise in the
// health chip next to the experiment's status.
export type ExperimentHealthUi = 'panel' | 'warnings'

export function experimentHealthUi(experiment: Experiment, showsServerHealth: boolean): ExperimentHealthUi {
    // A legacy experiment opens the legacy view, which shows the separate warnings also when the page shows
    // the server's findings.
    return showsServerHealth && !isLegacyExperiment(experiment) ? 'panel' : 'warnings'
}

export function healthFindingForExperimentWarning(warningKey: ExperimentWarningKey): ExperimentHealthFinding {
    return { code: EXPERIMENT_WARNING_FINDING_CODES[warningKey], variant: warningKey }
}

function isExperimentWarningKey(subcode: string | null): subcode is ExperimentWarningKey {
    return subcode !== null && Object.hasOwn(EXPERIMENT_WARNING_FINDING_CODES, subcode)
}

/** The flag-state warning among the server's findings. The server sends the warning key as the subcode. */
export function experimentWarningFromHealth(health: ExperimentHealthApi): ExperimentWarning | null {
    for (const finding of health.findings) {
        const { subcode } = finding
        if (isExperimentWarningKey(subcode) && EXPERIMENT_WARNING_FINDING_CODES[subcode] === finding.code) {
            if (subcode !== 'running_but_single_variant_shipped') {
                return { key: subcode }
            }
            const variantKey = finding.evidence.variant_key
            return { key: subcode, variantKey: typeof variantKey === 'string' ? variantKey : null }
        }
    }
    return null
}

// These events are read in aggregate, so they carry ids, codes and counts only. The experiment
// name, the flag key and the metric definitions are customer text, so do not spread
// `getEventPropertiesForExperiment` in.
function healthFindingEventProperties(
    experiment: Experiment,
    finding: ExperimentHealthFinding,
    healthUi: ExperimentHealthUi
): Record<string, string | number | null> {
    return {
        experiment_id: experiment.id,
        experiment_status: getExperimentStatus(experiment),
        experiment_days_since_start: experiment.start_date ? dayjs().diff(experiment.start_date, 'day') : null,
        finding_code: finding.code,
        finding_variant: finding.variant ?? null,
        finding_severity: finding.severity ?? null,
        finding_reason: finding.reason ?? null,
        health_ui: healthUi,
        surface: 'experiment_page',
        // The value the backend reports for a request from the web app, so one breakdown covers both.
        source: 'web',
    }
}

export function healthFindingReason(evidence: ExperimentHealthFindingApi['evidence']): string | undefined {
    return typeof evidence.reason === 'string' ? evidence.reason : undefined
}

function trackedHealthFinding({ code, subcode, severity, evidence }: ExperimentHealthFindingApi): string {
    // pinned: `code:subcode:severity:reason`, as on the server's `experiment launched`. Insights split each string
    // on `:`, so every field is present, empty when the finding has none.
    return [code, subcode ?? '', severity, healthFindingReason(evidence) ?? ''].join(':')
}

export function captureExperimentHealthFindingShown(
    experiment: Experiment,
    finding: ExperimentHealthFinding,
    healthUi: ExperimentHealthUi
): void {
    // pinned: analytics event name, so renaming it breaks insights
    posthog.capture('experiment health finding shown', healthFindingEventProperties(experiment, finding, healthUi))
}

export function captureExperimentHealthFindingOpened(
    experiment: Experiment,
    finding: ExperimentHealthFinding,
    healthUi: ExperimentHealthUi,
    openKind: ExperimentHealthFindingOpenKind
): void {
    // pinned: analytics event name, so renaming it breaks insights
    posthog.capture('experiment health finding opened', {
        ...healthFindingEventProperties(experiment, finding, healthUi),
        open_kind: openKind,
    })
}

export function captureExperimentHealthFindingActedOn(
    experiment: Experiment,
    finding: ExperimentHealthFinding,
    healthUi: ExperimentHealthUi,
    actionKind: ExperimentHealthFindingActionKind
): void {
    // pinned: analytics event name, so renaming it breaks insights
    posthog.capture('experiment health finding acted on', {
        ...healthFindingEventProperties(experiment, finding, healthUi),
        action_kind: actionKind,
        // A click starts the action. The save that completes it happens in a modal or on another page.
        action_step: 'started',
    })
}

export function captureExperimentHealthChecksOpened(
    experiment: Experiment,
    checks: HealthPanelCheck[],
    findingCount: number,
    healthUi: ExperimentHealthUi,
    openedFrom: ExperimentHealthChecksOpenedFrom
): void {
    // pinned: analytics event name, so renaming it breaks insights
    posthog.capture('experiment health checks opened', {
        experiment_id: experiment.id,
        experiment_status: getExperimentStatus(experiment),
        health_ui: healthUi,
        health_finding_count: findingCount,
        checks_passed: countHealthChecks(checks, 'passed'),
        checks_finding: countHealthChecks(checks, 'finding'),
        checks_not_applicable: countHealthChecks(checks, 'not_applicable'),
        checks_not_checked: countHealthChecks(checks, 'not_checked'),
        opened_from: openedFrom,
        surface: 'experiment_page',
    })
}

/**
 * Compares the page's own rules with the server's checks for one experiment load. A `_browser` value is the
 * result of the page's rule, and a `_server` value is the result of the server's check.
 *
 * `health` is null when the request failed. The event then has `request_failed` set, and its finding and
 * `_server` values are null. A failed request still reports `duration_ms`, so a request that times out
 * counts in the slow tail of the request time.
 */
export function captureExperimentHealthChecked(
    experiment: Experiment,
    health: ExperimentHealthApi | null,
    healthUi: ExperimentHealthUi,
    browserWarning: ExperimentWarning | null,
    browserNoMetricsWarning: boolean,
    durationMs: number
): void {
    const findings = health?.findings ?? null
    const flagStateFinding = findings?.find((finding) => FLAG_STATE_FINDING_CODES.has(finding.code))
    // pinned: analytics event name, so renaming it breaks insights
    posthog.capture('experiment health checked', {
        experiment_id: experiment.id,
        experiment_status: getExperimentStatus(experiment),
        health_ui: healthUi,
        request_failed: health === null,
        duration_ms: durationMs,
        health_finding_codes: findings?.map((finding) => finding.code) ?? null,
        // pinned: `code:subcode`, as on the server's `experiment launched`. The code prefix keeps a subcode
        // unambiguous when two codes use the same subcode.
        health_finding_subcodes:
            findings?.flatMap(({ code, subcode }) => (subcode ? [`${code}:${subcode}`] : [])) ?? null,
        health_findings: findings?.map(trackedHealthFinding) ?? null,
        health_finding_count: findings?.length ?? null,
        flag_state_browser: browserWarning?.key ?? null,
        // The server sends the warning key as the subcode. A finding without one still differs from no finding.
        flag_state_server: flagStateFinding ? (flagStateFinding.subcode ?? flagStateFinding.code) : null,
        no_metric_browser: browserNoMetricsWarning,
        no_metric_server: findings ? findings.some((finding) => finding.code === 'no_metric') : null,
    })
}

/**
 * The exposure warnings render on one tab only, so a "shown" event cannot give the exposure state of
 * every load. `experiment results refresh completed` follows the exposure load on every tab.
 * `has_srm`, `has_bias_risk` and a zero `exposures_total` are the page's own rules. The `_server` values are
 * the server's checks on the same answer, null when the answer holds no server findings (a cached answer
 * from before the server ran them).
 */
export function exposureHealthEventProperties(
    exposures: ExperimentExposureQueryResponse | null | undefined,
    multipleVariantHandling: ExperimentExposureCriteria['multiple_variant_handling']
): {
    exposures_total: number | null
    exposures_multiple: number | null
    has_srm: boolean | null
    has_bias_risk: boolean | null
    srm_server: boolean | null
    zero_exposures_server: boolean | null
    bias_risk_server: boolean | null
} {
    if (!exposures) {
        return {
            exposures_total: null,
            exposures_multiple: null,
            has_srm: null,
            has_bias_risk: null,
            srm_server: null,
            zero_exposures_server: null,
            bias_risk_server: null,
        }
    }
    const serverCodes = exposures.health_findings ? new Set(exposures.health_findings.map(({ code }) => code)) : null
    return {
        exposures_total: getTotalExposures(exposures),
        // With "first seen" handling the exposure query gives each person their first variant and
        // counts no `$multiple`, so the number of people in several variants is unknown there.
        exposures_multiple:
            multipleVariantHandling === 'first_seen'
                ? null
                : Number(exposures.total_exposures?.[EXPERIMENT_VARIANT_MULTIPLE] || 0),
        has_srm: hasSampleRatioMismatch(exposures),
        has_bias_risk: exposures.bias_risk != null,
        srm_server: serverCodes ? serverCodes.has('srm') : null,
        zero_exposures_server: serverCodes ? serverCodes.has('zero_exposures') : null,
        bias_risk_server: serverCodes ? serverCodes.has('bias_risk_multiple_excluded') : null,
    }
}
