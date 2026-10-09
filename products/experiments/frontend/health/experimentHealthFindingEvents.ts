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

// pinned: `finding_code` property values. Insights group and filter on them, so a rename breaks those insights.
export type ExperimentHealthFindingCode =
    | 'flag_off_while_running'
    | 'variant_shipped_while_running'
    | 'flag_live_after_end'
    | 'flag_live_before_launch'
    | 'bias_risk_multiple_excluded'
    | 'srm'
    | 'zero_exposures'
    | 'no_metric'

export interface ExperimentHealthFinding {
    code: ExperimentHealthFindingCode
    /** The sub-case of the code, for example the warning key. It must not hold customer text. */
    variant?: string
}

// pinned: `open_kind` property values, for the same reason as the codes above.
export type ExperimentHealthFindingOpenKind = 'evidence' | 'docs' | 'why'

// pinned: `action_kind` property values, for the same reason as the codes above.
export type ExperimentHealthFindingActionKind =
    | 'adjust_distribution'
    | 'use_first_seen_variant'
    | 'open_feature_flag'
    | 'edit_exposure_criteria'
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

// pinned: `health_ui` property values. Insights compare the health panel with the separate warnings on them.
export type ExperimentHealthUi = 'panel' | 'warnings'

export function experimentHealthUi(experiment: Experiment): ExperimentHealthUi {
    // The page shows the health panel only when the server sent health findings, which it does for readers
    // with the experiment-health-findings flag. A legacy experiment opens the legacy view, which shows the
    // separate warnings even then.
    return experiment.health && !isLegacyExperiment(experiment) ? 'panel' : 'warnings'
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
    finding: ExperimentHealthFinding
): Record<string, string | number | null> {
    return {
        experiment_id: experiment.id,
        experiment_status: getExperimentStatus(experiment),
        experiment_days_since_start: experiment.start_date ? dayjs().diff(experiment.start_date, 'day') : null,
        finding_code: finding.code,
        finding_variant: finding.variant ?? null,
        health_ui: experimentHealthUi(experiment),
        surface: 'experiment_page',
        // The value the backend reports for a request from the web app, so one breakdown covers both.
        source: 'web',
    }
}

export function captureExperimentHealthFindingShown(experiment: Experiment, finding: ExperimentHealthFinding): void {
    // pinned: analytics event name, so renaming it breaks insights
    posthog.capture('experiment health finding shown', healthFindingEventProperties(experiment, finding))
}

export function captureExperimentHealthFindingOpened(
    experiment: Experiment,
    finding: ExperimentHealthFinding,
    openKind: ExperimentHealthFindingOpenKind
): void {
    // pinned: analytics event name, so renaming it breaks insights
    posthog.capture('experiment health finding opened', {
        ...healthFindingEventProperties(experiment, finding),
        open_kind: openKind,
    })
}

export function captureExperimentHealthFindingActedOn(
    experiment: Experiment,
    finding: ExperimentHealthFinding,
    actionKind: ExperimentHealthFindingActionKind
): void {
    // pinned: analytics event name, so renaming it breaks insights
    posthog.capture('experiment health finding acted on', {
        ...healthFindingEventProperties(experiment, finding),
        action_kind: actionKind,
        // A click starts the action. The save that completes it happens in a modal or on another page.
        action_step: 'started',
    })
}

export interface ExperimentViewedHealthProperties {
    health_ui: ExperimentHealthUi
    health_finding_codes: ExperimentHealthFindingApi['code'][] | null
    health_finding_count: number | null
    flag_state_browser: string | null
    flag_state_server: string | null
    no_metric_browser: boolean
    no_metric_server: boolean | null
}

/**
 * The health state of one experiment load, for `experiment viewed`. A `_browser` value is the result of the
 * page's own rule, and a `_server` value is the result of the server's check, so every load compares the two.
 * The server values are null when the server sent no health findings.
 */
export function experimentHealthStateEventProperties(
    experiment: Experiment,
    browserWarning: ExperimentWarning | null,
    browserNoMetricsWarning: boolean
): ExperimentViewedHealthProperties {
    const { health } = experiment
    const flagStateFinding = health?.findings.find((finding) => FLAG_STATE_FINDING_CODES.has(finding.code))
    return {
        health_ui: experimentHealthUi(experiment),
        health_finding_codes: health ? health.findings.map((finding) => finding.code) : null,
        health_finding_count: health ? health.findings.length : null,
        flag_state_browser: browserWarning?.key ?? null,
        // The server sends the warning key as the subcode. A finding without one still differs from no finding.
        flag_state_server: flagStateFinding ? (flagStateFinding.subcode ?? flagStateFinding.code) : null,
        no_metric_browser: browserNoMetricsWarning,
        no_metric_server: health ? health.findings.some((finding) => finding.code === 'no_metric') : null,
    }
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
