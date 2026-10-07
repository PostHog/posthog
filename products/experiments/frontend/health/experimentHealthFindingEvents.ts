import { dayjs } from 'lib/dayjs'
import posthog from 'lib/posthog-typed'
import type { ExperimentWarningKey } from 'scenes/experiments/experimentLogic'

import type { ExperimentExposureCriteria, ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { EXPERIMENT_VARIANT_MULTIPLE } from '../constants'
import { getExperimentStatus } from '../experimentStatus'
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
export type ExperimentHealthFindingOpenKind = 'evidence' | 'docs'

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

export function healthFindingForExperimentWarning(warningKey: ExperimentWarningKey): ExperimentHealthFinding {
    return { code: EXPERIMENT_WARNING_FINDING_CODES[warningKey], variant: warningKey }
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

/**
 * The exposure warnings render on one tab only, so a "shown" event cannot give the exposure state of
 * every load. `experiment results refresh completed` follows the exposure load on every tab.
 */
export function exposureHealthEventProperties(
    exposures: ExperimentExposureQueryResponse | null | undefined,
    multipleVariantHandling: ExperimentExposureCriteria['multiple_variant_handling']
): {
    exposures_total: number | null
    exposures_multiple: number | null
    has_srm: boolean | null
    has_bias_risk: boolean | null
} {
    if (!exposures) {
        return { exposures_total: null, exposures_multiple: null, has_srm: null, has_bias_risk: null }
    }
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
    }
}
