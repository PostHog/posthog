import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { AlertEvaluationHistoryChart } from 'products/alerts/frontend/components/AlertEvaluationHistoryChart'
import {
    LogsAlertConfigurationApi,
    LogsAlertEventApi,
    LogsAlertEventKindEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { describeEvent, getHistoryPoints, getHistoryThresholds } from './logsAlertEventDescriptions'
import { LogsAlertEventHistoryLogicProps, logsAlertEventHistoryLogic } from './logsAlertEventHistoryLogic'

export function LogsAlertEventHistoryContent({ alert }: { alert: LogsAlertConfigurationApi }): JSX.Element {
    const logicProps: LogsAlertEventHistoryLogicProps = { alertId: alert.id }

    return (
        <BindLogic logic={logsAlertEventHistoryLogic} props={logicProps}>
            <LogsAlertEventTimeline alert={alert} />
        </BindLogic>
    )
}

function LogsAlertEventTimeline({ alert }: { alert: LogsAlertConfigurationApi }): JSX.Element {
    const { eventsPage, eventsPageLoading } = useValues(logsAlertEventHistoryLogic)
    const { loadMore } = useActions(logsAlertEventHistoryLogic)
    const historyPoints = getHistoryPoints(eventsPage.results)

    const columns: LemonTableColumns<LogsAlertEventApi> = [
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

    const hasMore = eventsPage.next !== null
    const shownOf =
        eventsPage.count > eventsPage.results.length
            ? ` · Showing ${eventsPage.results.length} of ${eventsPage.count}`
            : ''

    return (
        <div className="space-y-4">
            {historyPoints.length > 0 ? (
                <AlertEvaluationHistoryChart
                    points={historyPoints}
                    valueLabel="Matching logs"
                    thresholds={getHistoryThresholds(alert)}
                    historyLimit={Math.max(historyPoints.length, 1)}
                    evaluationNoun="evaluation"
                />
            ) : null}
            <div className="max-h-96 overflow-y-auto">
                <LemonTable
                    columns={columns}
                    dataSource={eventsPage.results}
                    rowKey="id"
                    loading={eventsPageLoading}
                    emptyState="No events yet. Evaluations, transitions, and user actions will appear here."
                    size="small"
                    expandable={{
                        rowExpandable: () => true,
                        expandedRowRender: (event) => <LogsAlertEventDetails event={event} />,
                    }}
                />
            </div>
            {hasMore ? (
                <div className="flex justify-center">
                    <LemonButton type="secondary" size="small" onClick={loadMore} loading={eventsPageLoading}>
                        Load more{shownOf}
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

function LogsAlertEventDetails({ event }: { event: LogsAlertEventApi }): JSX.Element {
    return (
        <dl className="px-3 py-2 text-xs grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted">Kind</dt>
            <dd className="font-mono">{event.kind}</dd>
            <dt className="text-muted">State</dt>
            <dd className="font-mono">
                {event.state_before} → {event.state_after}
            </dd>
            {event.kind === LogsAlertEventKindEnumApi.Check ? (
                <>
                    <dt className="text-muted">Breached</dt>
                    <dd className="font-mono">{event.threshold_breached ? 'yes' : 'no'}</dd>
                </>
            ) : null}
            {event.result_count !== null ? (
                <>
                    <dt className="text-muted">Result count</dt>
                    <dd className="font-mono">{event.result_count}</dd>
                </>
            ) : null}
            {event.query_duration_ms !== null ? (
                <>
                    <dt className="text-muted">Query duration</dt>
                    <dd className="font-mono">{event.query_duration_ms} ms</dd>
                </>
            ) : null}
            {event.error_message ? (
                <>
                    <dt className="text-muted">Error</dt>
                    <dd className="font-mono whitespace-pre-wrap break-words">{event.error_message}</dd>
                </>
            ) : null}
            <dt className="text-muted">Timestamp</dt>
            <dd className="font-mono">
                <TZLabel time={event.created_at} />
            </dd>
        </dl>
    )
}
