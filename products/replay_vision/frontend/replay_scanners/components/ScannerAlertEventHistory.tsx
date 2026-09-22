import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import {
    AlertEvaluationHistoryChart,
    AlertEvaluationHistoryPoint,
    AlertEvaluationThreshold,
} from 'products/alerts/frontend/components/AlertEvaluationHistoryChart'

import type { VisionAlertConfigurationApi, VisionAlertEventApi } from '../../generated/api.schemas'
import { ScannerAlertEventsLogicProps, scannerAlertEventsLogic } from '../scannerAlertEventsLogic'

export function ScannerAlertEventHistory({ alert }: { alert: VisionAlertConfigurationApi }): JSX.Element {
    const logicProps: ScannerAlertEventsLogicProps = { alertId: alert.id }
    return (
        <BindLogic logic={scannerAlertEventsLogic} props={logicProps}>
            <ScannerAlertEventTimeline alert={alert} />
        </BindLogic>
    )
}

function describeEvent(event: VisionAlertEventApi): { label: string; type: LemonTagType; detail?: string } {
    if (event.kind !== 'check') {
        const labels: Record<string, string> = {
            reset: 'Reset',
            enable: 'Enabled',
            disable: 'Disabled',
            snooze: 'Snoozed',
            unsnooze: 'Unsnoozed',
            threshold_change: 'Condition changed',
        }
        return { label: labels[event.kind] ?? event.kind, type: 'default' }
    }
    if (event.error_message) {
        return { label: 'Check failed', type: 'danger', detail: event.error_message }
    }
    if (event.state_after === 'firing' && event.state_before !== 'firing') {
        return { label: 'Fired', type: 'danger' }
    }
    if (event.state_before === 'firing' && event.state_after === 'not_firing') {
        return { label: 'Resolved', type: 'success' }
    }
    return { label: 'Checked', type: 'default' }
}

function getHistoryThresholds(alert: VisionAlertConfigurationApi): AlertEvaluationThreshold[] {
    const thresholdValue = alert.threshold ?? 0
    if (alert.direction === 'below') {
        return [{ direction: 'lower', value: thresholdValue, label: `At or below (${thresholdValue})` }]
    }
    return [{ direction: 'upper', value: thresholdValue, label: `At or above (${thresholdValue})` }]
}

function getHistoryPoints(events: VisionAlertEventApi[]): AlertEvaluationHistoryPoint[] {
    return events
        .filter((event) => event.kind === 'check' && event.metric_value !== null && event.metric_value !== undefined)
        .sort((left, right) => left.created_at.localeCompare(right.created_at))
        .map((event) => ({
            label: dayjs(event.created_at).format('MMM D, HH:mm'),
            value: event.metric_value ?? 0,
            firedAtTime: event.state_after === 'firing',
        }))
}

function ScannerAlertEventTimeline({ alert }: { alert: VisionAlertConfigurationApi }): JSX.Element {
    const { eventsPage, eventsPageLoading } = useValues(scannerAlertEventsLogic)
    const { loadMore } = useActions(scannerAlertEventsLogic)
    const historyPoints = getHistoryPoints(eventsPage.results)

    const columns: LemonTableColumns<VisionAlertEventApi> = [
        {
            title: 'Event',
            render: (_, event) => {
                const { label, type } = describeEvent(event)
                return <LemonTag type={type}>{label}</LemonTag>
            },
        },
        {
            title: 'When',
            render: (_, event) => <TZLabel time={event.created_at} formatDate="MMM D" formatTime="HH:mm:ss" />,
        },
        {
            title: 'Detail',
            render: (_, event) => {
                const { detail } = describeEvent(event)
                return detail ? <span className="text-muted text-xs">{detail}</span> : null
            },
        },
    ]

    return (
        <div className="space-y-4">
            {alert.kind === 'metric' ? (
                <AlertEvaluationHistoryChart
                    points={historyPoints}
                    valueLabel={alert.metric === 'avg_score' ? 'Average score' : 'Matching observations'}
                    thresholds={getHistoryThresholds(alert)}
                    historyLimit={100}
                    evaluationNoun="check"
                />
            ) : null}
            <LemonTable
                columns={columns}
                dataSource={eventsPage.results}
                loading={eventsPageLoading}
                rowKey="id"
                emptyState="No history yet. Events appear after the first check runs."
                data-attr="vision-alert-event-history"
            />
            {eventsPage.next ? (
                <LemonButton type="secondary" size="small" onClick={loadMore} loading={eventsPageLoading}>
                    Load more
                </LemonButton>
            ) : null}
        </div>
    )
}
