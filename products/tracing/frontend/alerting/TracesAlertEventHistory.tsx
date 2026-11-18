import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { truncate } from 'lib/utils/strings'

import {
    AlertEvaluationHistoryChart,
    AlertEvaluationHistoryPoint,
    AlertEvaluationThreshold,
} from 'products/alerts/frontend/components/AlertEvaluationHistoryChart'
import {
    PlatformAlertConfigurationApi,
    PlatformAlertEventApi,
    PlatformAlertEventKindEnumApi,
    TracesAlertThresholdOperatorApi,
    TracesPlatformAlertConditionApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import { tracesAlertEventHistoryLogic } from './tracesAlertEventHistoryLogic'
import { formatMeasured, measureLabel, tracesSourceConfig } from './tracesAlertUtils'

export function TracesAlertEventHistory({ alert }: { alert: PlatformAlertConfigurationApi }): JSX.Element {
    const groupNames = Object.fromEntries(
        alert.alerts.map((instance) => [instance.grouping_key, Object.values(instance.labels).join(' · ')])
    )
    return (
        <BindLogic logic={tracesAlertEventHistoryLogic} props={{ alertId: alert.id }}>
            <TracesAlertEventTimeline condition={tracesSourceConfig(alert)?.condition} groupNames={groupNames} />
        </BindLogic>
    )
}

/** The condition a check was evaluated against, as recorded with it. Older checks may hold another measure. */
function checkedCondition(event: PlatformAlertEventApi): TracesPlatformAlertConditionApi | undefined {
    const condition = event.condition as Partial<TracesPlatformAlertConditionApi>
    return condition.measure && typeof condition.threshold === 'number'
        ? (condition as TracesPlatformAlertConditionApi)
        : undefined
}

// The chart plots an error rate as a percentage, so its axis reads in the same unit as the labels.
function charted(condition: TracesPlatformAlertConditionApi, value: number): number {
    return condition.measure === 'error_rate' ? value * 100 : value
}

function historyThresholds(condition: TracesPlatformAlertConditionApi): AlertEvaluationThreshold[] {
    const label = `${condition.threshold_operator === TracesAlertThresholdOperatorApi.Below ? 'Below' : 'Above'} (${formatMeasured(condition, condition.threshold)})`
    return [
        {
            direction: condition.threshold_operator === TracesAlertThresholdOperatorApi.Below ? 'lower' : 'upper',
            value: charted(condition, condition.threshold),
            label,
        },
    ]
}

/** Checks in the current condition's measure only, because one axis cannot hold a count and a latency. */
function historyPoints(
    events: PlatformAlertEventApi[],
    condition: TracesPlatformAlertConditionApi
): AlertEvaluationHistoryPoint[] {
    return events
        .filter(
            (event) =>
                event.kind === PlatformAlertEventKindEnumApi.Check &&
                event.value !== null &&
                (checkedCondition(event)?.measure ?? condition.measure) === condition.measure
        )
        .sort((left, right) => left.occurred_at.localeCompare(right.occurred_at))
        .map((event) => ({
            label: dayjs(event.occurred_at).format('MMM D, HH:mm'),
            value: charted(condition, event.value ?? 0),
            firedAtTime: event.state === 'firing',
        }))
}

function TracesAlertEventTimeline({
    condition,
    groupNames,
}: {
    condition: TracesPlatformAlertConditionApi | undefined
    groupNames: Record<string, string>
}): JSX.Element {
    const { events, eventsLoading, eventsLoadFailed } = useValues(tracesAlertEventHistoryLogic)
    const { loadEvents } = useActions(tracesAlertEventHistoryLogic)
    const points = condition ? historyPoints(events, condition) : []

    const columns: LemonTableColumns<PlatformAlertEventApi> = [
        {
            title: 'Event',
            render: (_, event) => {
                const { label, type } = describeEvent(event, condition)
                return <LemonTag type={type}>{label}</LemonTag>
            },
        },
        {
            title: 'When',
            render: (_, event) => <TZLabel time={event.occurred_at} formatDate="MMM D" formatTime="HH:mm:ss" />,
        },
        {
            title: 'Detail',
            render: (_, event) => {
                const { detail } = describeEvent(event, condition)
                const group = event.grouping_key ? groupNames[event.grouping_key] : undefined
                const shown = [group, detail].filter(Boolean).join(' · ')
                return shown ? <span className="text-muted text-xs">{shown}</span> : null
            },
        },
    ]

    if (eventsLoadFailed && !eventsLoading) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadEvents() }}>
                Could not load this alert's history. Retry, and if it keeps failing, contact support.
            </LemonBanner>
        )
    }

    return (
        <div className="space-y-4">
            {condition && points.length > 0 ? (
                <AlertEvaluationHistoryChart
                    points={points}
                    valueLabel={measureLabel(condition)}
                    thresholds={historyThresholds(condition)}
                    historyLimit={Math.max(points.length, 1)}
                    evaluationNoun="check"
                />
            ) : null}
            <div className="max-h-96 overflow-y-auto">
                <LemonTable
                    columns={columns}
                    dataSource={events}
                    rowKey={(event) => `${event.kind}-${event.occurred_at}-${event.grouping_key}`}
                    loading={eventsLoading}
                    emptyState="No history yet. Checks that change the alert's state, and changes people make, appear here."
                    size="small"
                />
            </div>
        </div>
    )
}

interface EventDescription {
    label: string
    type: LemonTagType
    detail: string | null
}

const CONTROL_PLANE_DESCRIPTIONS: Record<
    Exclude<PlatformAlertEventKindEnumApi, typeof PlatformAlertEventKindEnumApi.Check>,
    Pick<EventDescription, 'label' | 'type'>
> = {
    [PlatformAlertEventKindEnumApi.Reset]: { label: 'Reset', type: 'primary' },
    [PlatformAlertEventKindEnumApi.Enable]: { label: 'Enabled', type: 'success' },
    [PlatformAlertEventKindEnumApi.Disable]: { label: 'Disabled', type: 'muted' },
    [PlatformAlertEventKindEnumApi.Snooze]: { label: 'Snoozed', type: 'highlight' },
    [PlatformAlertEventKindEnumApi.Unsnooze]: { label: 'Unsnoozed', type: 'highlight' },
    [PlatformAlertEventKindEnumApi.ConfigChange]: { label: 'Settings changed', type: 'completion' },
}

function describeEvent(
    event: PlatformAlertEventApi,
    current: TracesPlatformAlertConditionApi | undefined
): EventDescription {
    if (event.kind !== PlatformAlertEventKindEnumApi.Check) {
        return {
            ...CONTROL_PLANE_DESCRIPTIONS[event.kind],
            detail: event.previous_state === event.state ? null : `${event.previous_state} → ${event.state}`,
        }
    }
    // A check's value reads in the unit of the condition it was checked against, not today's.
    const condition = checkedCondition(event) ?? current
    const measured =
        event.value !== null && condition
            ? `${measureLabel(condition)} ${formatMeasured(condition, event.value)}`
            : null
    if (event.error_message && event.state === 'broken') {
        return { label: 'Auto-disabled', type: 'caution', detail: truncate(event.error_message, 80) }
    }
    if (event.error_message) {
        return { label: 'Errored', type: 'warning', detail: truncate(event.error_message, 80) }
    }
    if (event.previous_state !== 'firing' && event.state === 'firing') {
        return { label: 'Fired', type: 'danger', detail: measured ? `${measured} · threshold breached` : null }
    }
    if (event.previous_state === 'firing' && event.state !== 'firing') {
        return { label: 'Resolved', type: 'success', detail: measured ? `${measured} · back to normal` : null }
    }
    return { label: 'Check', type: 'default', detail: measured }
}
