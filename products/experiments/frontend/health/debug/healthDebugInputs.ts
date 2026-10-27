import type { Experiment } from '~/types'

import { EXPERIMENT_VARIANT_MULTIPLE } from '../../constants'
import { getExperimentStatus } from '../../experimentStatus'
import type {
    ExperimentHealthInputsApi,
    ExperimentHealthInputsExposuresApi,
    ExperimentHealthInputsTrafficStatusEnumApi,
    HealthExposureInputsStatusEnumApi,
} from '../../generated/api.schemas'
import type { SetupFact } from '../../setupInspector/SetupFactsTable'
import { formatCount, formatShare, formatTimestamp, formatYesNo } from '../../setupInspector/setupInspectorUtils'

export interface HealthInputsState {
    inputs: ExperimentHealthInputsApi | null
    loading: boolean
    error: string | null
}

export interface HealthDebugReleaseCondition {
    number: number
    rolloutPercentage: number | null
    propertyCount: number | null
    reachable: boolean
    pinnedVariant: string | null
    /** People this condition served in the traffic window. Null when the traffic was not read. */
    people: number | null
}

export interface HealthDebugFlagChange {
    changedAt: string
    /** What changed: the split, a setting that decides the variant draw, or the release conditions. */
    changed: string
    before: string
    after: string
    counted: boolean
}

export interface PageMetricCounts {
    primary: number
    secondary: number
}

function serverValue(state: HealthInputsState, read: (inputs: ExperimentHealthInputsApi) => string): string {
    if (state.inputs) {
        return read(state.inputs)
    }
    if (state.loading) {
        return 'Loading…'
    }
    return state.error ? `Not loaded: ${state.error}` : 'Not loaded'
}

function yesNoUnknown(value: boolean | null): string {
    return value === null ? 'Unknown' : formatYesNo(value)
}

function describeExposureEvents({ exposure_events, events_received }: ExperimentHealthInputsApi): string {
    if (!exposure_events) {
        return "The stored exposure criteria don't parse"
    }
    if (exposure_events.custom_event) {
        const received = events_received[exposure_events.custom_event]
        const receivedText = received === undefined ? 'no record' : received ? 'received' : 'never received'
        return `The event "${exposure_events.custom_event}" (${receivedText}), with the variant in ${exposure_events.variant_property}`
    }
    if (exposure_events.required_flag_key) {
        const calls = `Calls of the flag "${exposure_events.required_flag_key}"`
        return exposure_events.activation ? `${calls}, then the activation "${exposure_events.activation}"` : calls
    }
    return `An action, with the variant in ${exposure_events.variant_property}`
}

function describeState(inputs: ExperimentHealthInputsApi): string {
    if (!inputs.is_launched) {
        return 'not launched'
    }
    const states = [
        inputs.is_running && 'running',
        inputs.is_paused && 'paused',
        inputs.has_ended && 'ended',
        inputs.archived && 'archived',
    ].filter(Boolean)
    return ['launched', ...states].join(', ')
}

export function buildExperimentFacts(
    experiment: Experiment,
    state: HealthInputsState,
    hoursSinceStart: number | null
): SetupFact[] {
    return [
        { label: 'Status on the page', value: getExperimentStatus(experiment) },
        {
            label: 'State the checks read',
            value: serverValue(state, describeState),
            help: 'The flag-state, flag-change and forced-variant checks only fire for some of these states.',
        },
        { label: 'Start date', value: formatTimestamp(experiment.start_date) },
        {
            label: 'Hours since start',
            value: hoursSinceStart === null ? 'Not launched' : String(Math.floor(hoursSinceStart)),
            help: 'The zero-exposures finding waits for a few hours after launch.',
        },
        { label: 'End date', value: formatTimestamp(experiment.end_date) },
        {
            label: 'Baseline variant',
            value: serverValue(state, (inputs) => inputs.baseline_variant_key ?? 'Not set, the analysis picks one'),
            help: 'The flag-variants check needs the baseline to be one of the flag variants.',
        },
        {
            label: 'Excluded from the analysis',
            value: serverValue(state, (inputs) => inputs.excluded_variant_keys.join(', ') || 'None'),
            help: 'The forced-variant check ignores pins to these variants.',
        },
        {
            label: 'Your access',
            value: serverValue(
                state,
                ({ reader_access }) =>
                    `Flag history: ${formatYesNo(reader_access.can_read_flag_history).toLowerCase()}. Event queries: ${formatYesNo(reader_access.can_query_events).toLowerCase()}. Denied event properties: ${reader_access.denied_event_properties.join(', ') || 'none'}.`
            ),
            help: 'The flag-change and forced-variant checks read only what the person loading the page may read. A customer without this access gets other findings than you.',
        },
    ]
}

export function buildFlagFacts(experiment: Experiment, state: HealthInputsState): SetupFact[] {
    return [
        { label: 'Key', value: experiment.feature_flag?.key ?? 'None' },
        {
            label: 'Enabled',
            value: serverValue(state, ({ flag }) => (flag ? formatYesNo(flag.active) : 'No flag')),
        },
        {
            label: 'Deleted',
            value: serverValue(state, ({ flag }) => (flag ? formatYesNo(flag.deleted) : 'No flag')),
        },
        {
            label: 'Variants',
            value: serverValue(state, ({ flag }) => (flag ? flag.split_text : 'No flag')),
        },
        {
            label: 'Latest recorded call',
            value: serverValue(state, ({ flag_last_called_at }) =>
                flag_last_called_at ? formatTimestamp(flag_last_called_at) : 'None'
            ),
            help: 'A sync of the flag call events sets it every 30 minutes, so it can trail a call by up to an hour.',
        },
        {
            label: 'Called during the run',
            value: serverValue(state, ({ flag_called_during_run }) => yesNoUnknown(flag_called_during_run)),
            help: "The zero-exposures finding says the flag has no recorded calls when this is No. Unknown before launch, when the latest call came after the end, or when the organization's flag calls skip the events table.",
        },
    ]
}

export function buildReleaseConditions(inputs: ExperimentHealthInputsApi | null): HealthDebugReleaseCondition[] {
    const traffic = inputs?.condition_set_traffic
    const peopleBySet = new Map(traffic?.people_by_set.map(({ condition_set, people }) => [condition_set, people]))
    return (inputs?.flag?.release_conditions ?? []).map((condition) => ({
        number: condition.number,
        rolloutPercentage: condition.rollout_percentage,
        propertyCount: condition.property_count,
        reachable: condition.reachable,
        pinnedVariant: condition.pinned_variant,
        people: traffic ? (peopleBySet.get(condition.number) ?? 0) : null,
    }))
}

function describeFlagHistoryStatus(inputs: ExperimentHealthInputsApi): string {
    const history = inputs.flag_history
    if (history) {
        if (!history.checked) {
            return `Not compared: ${history.not_checked_reason}`
        }
        const changes = history.changes
        const total = changes.length
        const counted = changes.filter((change) => change.counted).length
        if (total === 0) {
            return 'No changes since launch'
        }
        if (total === 1) {
            return counted
                ? 'Compared with the exposures: the change counts'
                : 'Compared with the exposures: nobody was exposed before the change, so it does not count'
        }
        return counted === 0
            ? `Compared with the exposures: nobody was exposed before any of the ${total} changes, so none counts`
            : `Compared with the exposures: ${counted} of ${total} changes count`
    }
    if (!inputs.is_running) {
        return 'Not read: the experiment is not running'
    }
    if (inputs.archived) {
        return 'Not read: the experiment is archived'
    }
    if (!inputs.flag || inputs.flag.deleted) {
        return 'Not read: the flag is missing or deleted'
    }
    return 'Not read: the read failed'
}

export function buildFlagHistoryFacts(state: HealthInputsState): SetupFact[] {
    const history = state.inputs?.flag_history ?? null
    const hasCountedChange = !!history && history.changes.some((change) => change.counted)
    return [
        {
            label: 'Status',
            value: serverValue(state, describeFlagHistoryStatus),
            help: 'The flag-change checks compare the changes with the exposures only for an exposure event without property filters. Every change counts from the first one, of any kind, with an exposure before it.',
        },
        ...(history
            ? [{ label: 'Launched at', value: `${formatTimestamp(history.launched_at)} (${history.team_timezone})` }]
            : []),
        ...(hasCountedChange && history
            ? [
                  {
                      label: 'Exposed before the first counted change',
                      value: yesNoUnknown(history.exposed_before_first),
                  },
                  ...history.exposed_between.map(({ question, exposed }) => ({
                      label: question,
                      value: yesNoUnknown(exposed),
                      help: 'Asked only when the last counted change of this kind sets back what the first changed.',
                  })),
              ]
            : []),
    ]
}

export function buildFlagChanges(inputs: ExperimentHealthInputsApi | null): HealthDebugFlagChange[] {
    return (inputs?.flag_history?.changes ?? []).map((change) => ({
        changedAt: formatTimestamp(change.changed_at),
        changed: change.changed,
        before: change.before,
        after: change.after,
        counted: change.counted,
    }))
}

const TRAFFIC_STATUS_LABELS: Record<ExperimentHealthInputsTrafficStatusEnumApi, string> = {
    read: 'Read',
    not_needed: 'Not read: no check needs it',
    no_query_access: 'Not read: you may not query events',
    denied_properties: 'Not read: you are denied a flag call property that the scan reads',
    no_flag_version: "Not read: the flag has no version, so its calls can't be matched to it",
    unknown: "Not read: the scan failed or was too expensive, or another request's scan did not answer in time",
}

export function buildTrafficFacts(state: HealthInputsState): SetupFact[] {
    const traffic = state.inputs?.condition_set_traffic ?? null
    const people = traffic?.people_by_set.reduce((sum, { people }) => sum + people, 0) ?? 0
    return [
        {
            label: 'Status',
            value: serverValue(state, (inputs) => TRAFFIC_STATUS_LABELS[inputs.condition_set_traffic_status]),
            help: 'The forced-variant check reads the calls when the experiment is launched and some, but not all, release conditions pin a variant that has a share of the split and is not excluded from the analysis. The release-condition check reads them when such an override was removed after launch. The flag-state check reads them when the experiment is running and the flag has a 0% rollout.',
        },
        ...(traffic
            ? [
                  { label: 'Since', value: `${formatTimestamp(traffic.since)} (${traffic.team_timezone})` },
                  { label: 'Calls', value: formatCount(traffic.calls) },
                  {
                      label: 'Evaluated by the flag service',
                      value: `${formatCount(traffic.remotely_evaluated_calls)} (${formatShare(traffic.calls ? traffic.remotely_evaluated_calls / traffic.calls : null)})`,
                      help: 'Only these calls name the condition that served them. Local evaluation and bootstrapped values name none.',
                  },
                  { label: 'People served by a named condition', value: formatCount(people) },
                  {
                      label: 'People assigned outside the flag service',
                      value: formatCount(traffic.people_assigned_outside),
                      help: 'People who got a variant from a call without a flag version that is no local evaluation, from an hour after the window starts. With a 0% rollout, 10 or more of them show that the variants are assigned outside PostHog.',
                  },
              ]
            : []),
    ]
}

export function buildMetricFacts(
    experiment: Experiment,
    state: HealthInputsState,
    pageMetricCounts: PageMetricCounts
): SetupFact[] {
    const sharedMetricTypes = (experiment.saved_metrics ?? []).map(
        (link: { metadata?: { type?: string } }) => link.metadata?.type ?? 'none'
    )
    const countType = (type: string): number => sharedMetricTypes.filter((linkType) => linkType === type).length
    return [
        {
            label: 'Metrics the checks count',
            value: serverValue(
                state,
                (inputs) => `${inputs.primary_metric_count} primary, ${inputs.secondary_metric_count} secondary`
            ),
            help: 'The no-metric check fires when both are zero.',
        },
        {
            label: 'Metrics the page lists',
            value: `${pageMetricCounts.primary} primary, ${pageMetricCounts.secondary} secondary`,
            help: "The browser's no-metric rule reads these.",
        },
        {
            label: 'Single-use metrics',
            value: `${experiment.metrics?.length ?? 0} primary, ${experiment.metrics_secondary?.length ?? 0} secondary`,
        },
        {
            label: 'Shared metric links',
            value: `${countType('primary')} primary, ${countType('secondary')} secondary, ${countType('none')} without a type`,
        },
    ]
}

const EXPOSURE_STATUS_LABELS: Record<HealthExposureInputsStatusEnumApi, string> = {
    ready: 'Read from the cache',
    stale: 'Read from the cache, which is past its age. A recalculation runs in the background.',
    calculating: 'No cached answer. A calculation runs in the background, so reload the inputs in a minute.',
    not_launched: 'None, the experiment is not launched',
    no_query_access: 'Not read: you may not query events',
    failed: 'The exposure query failed',
}

function exposureStatusLabel(exposures: ExperimentHealthInputsExposuresApi): string {
    if (!exposures.error) {
        return EXPOSURE_STATUS_LABELS[exposures.status]
    }
    // A stale answer with an error means the recalculation failed, and no new one runs yet.
    const label =
        exposures.status === 'stale'
            ? 'Read from the cache, which is past its age. The last recalculation failed'
            : EXPOSURE_STATUS_LABELS[exposures.status]
    return `${label}: ${exposures.error}`
}

export function buildExposureFacts(state: HealthInputsState): SetupFact[] {
    const exposures = state.inputs?.exposures
    const facts: SetupFact[] = [
        {
            label: 'Status',
            value: serverValue(state, (inputs) => exposureStatusLabel(inputs.exposures)),
            help: 'The server reads the cached answer and never waits for the query.',
        },
        {
            label: 'Counted on',
            value: serverValue(state, describeExposureEvents),
            help: "The zero-exposures finding reads the flag's calls only when the exposures are counted on them. A custom event or an action carries the variant in its own property.",
        },
    ]
    const totals = exposures?.totals
    if (!exposures || !totals) {
        return facts
    }
    const total = Object.values(totals.total_exposures).reduce((sum, count) => sum + count, 0)
    const byVariant = Object.entries(totals.total_exposures)
        .map(([variant, count]) => `${variant} ${formatCount(count)}`)
        .join(', ')
    const pValue = totals.sample_ratio_mismatch_p_value
    return [
        ...facts,
        { label: 'Computed at', value: formatTimestamp(exposures.computed_at) },
        {
            label: 'Hours since launch at computation',
            value: totals.hours_since_launch === null ? 'Not launched' : String(Math.floor(totals.hours_since_launch)),
            help: 'The zero-exposures check waits for a few hours after launch.',
        },
        {
            label: 'Exposed users',
            value: formatCount(total),
            help: `Includes the users in several variants, as the zero-exposures and bias checks count them.`,
        },
        { label: 'By variant', value: byVariant || 'None' },
        {
            label: 'Users in several variants',
            value: formatCount(totals.total_exposures[EXPERIMENT_VARIANT_MULTIPLE] ?? 0),
            help: `Reported as ${EXPERIMENT_VARIANT_MULTIPLE}.`,
        },
        { label: 'Multiple variant handling', value: totals.multiple_variant_handling },
        {
            label: 'Sample ratio test',
            value: pValue !== null ? `p = ${pValue.toPrecision(3)}` : 'Not run, too little data',
            help: 'The SRM finding needs p < 0.001.',
        },
        {
            label: 'Findings on this answer',
            value: exposures.findings.length
                ? exposures.findings.map((finding) => `${finding.code} (${finding.severity})`).join(', ')
                : 'None',
        },
    ]
}
