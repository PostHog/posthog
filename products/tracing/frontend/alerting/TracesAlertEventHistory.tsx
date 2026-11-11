import { BindLogic, useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

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
    return (
        <BindLogic logic={tracesAlertEventHistoryLogic} props={{ alertId: alert.id }}>
            <TracesAlertEventTimeline condition={tracesSourceConfig(alert)?.condition} />
        </BindLogic>
    )
}

function historyThresholds(condition: TracesPlatformAlertConditionApi): AlertEvaluationThreshold[] {
    const label = `${condition.threshold_operator === TracesAlertThresholdOperatorApi.Below ? 'Below' : 'Above'} (${formatMeasured(condition, condition.threshold)})`
    return [
        {
            direction: condition.threshold_operator === TracesAlertThresholdOperatorApi.Below ? 'lower' : 'upper',
            value: condition.threshold,
            label,
        },
    ]
}

function historyPoints(events: PlatformAlertEventApi[]): AlertEvaluationHistoryPoint[] {
    return events
        .filter((event) => event.kind === PlatformAlertEventKindEnumApi.Check && event.value !== null)
        .sort((left, right) => left.occurred_at.localeCompare(right.occurred_at))
        .map((event) => ({
            label: dayjs(event.occurred_at).format('MMM D, HH:mm'),
            value: event.value ?? 0,
            firedAtTime: event.state === 'firing',
        }))
}

function TracesAlertEventTimeline({
    condition,
}: {
    condition: TracesPlatformAlertConditionApi | undefined
}): JSX.Element {
    const { events, eventsLoading } = useValues(tracesAlertEventHistoryLogic)
    const points = historyPoints(events)

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
                return detail ? <span className="text-muted text-xs">{detail}</span> : null
            },
        },
    ]

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
                    rowKey={(event) => `${event.kind}-${event.occurred_at}`}
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
    condition: TracesPlatformAlertConditionApi | undefined
): EventDescription {
    if (event.kind !== PlatformAlertEventKindEnumApi.Check) {
        return {
            ...CONTROL_PLANE_DESCRIPTIONS[event.kind],
            detail: event.previous_state === event.state ? null : `${event.previous_state} → ${event.state}`,
        }
    }
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
