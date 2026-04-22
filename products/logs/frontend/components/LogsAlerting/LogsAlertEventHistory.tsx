import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { truncate } from 'lib/utils'

import {
    LogsAlertConfigurationApi,
    LogsAlertEventApi,
    LogsAlertEventKindEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertEventHistoryLogicProps, logsAlertEventHistoryLogic } from './logsAlertEventHistoryLogic'

interface LogsAlertEventHistoryModalProps {
    alert: LogsAlertConfigurationApi | null
    onClose: () => void
}

export function LogsAlertEventHistoryModal({ alert, onClose }: LogsAlertEventHistoryModalProps): JSX.Element {
    return (
        <LemonModal isOpen={alert !== null} onClose={onClose} width={640} title="" simple>
            {alert ? <LogsAlertEventHistoryContent alert={alert} /> : null}
        </LemonModal>
    )
}

function LogsAlertEventHistoryContent({ alert }: { alert: LogsAlertConfigurationApi }): JSX.Element {
    const logicProps: LogsAlertEventHistoryLogicProps = { alertId: alert.id }

    return (
        <BindLogic logic={logsAlertEventHistoryLogic} props={logicProps}>
            <LemonModal.Header>
                <h3 className="flex items-center gap-2">
                    Alert history
                    <span className="text-muted text-sm font-normal">· {alert.name}</span>
                </h3>
                <p className="text-muted text-sm m-0">Transitions, errors, and user actions.</p>
            </LemonModal.Header>
            <LemonModal.Content>
                <LogsAlertEventTimeline />
            </LemonModal.Content>
        </BindLogic>
    )
}

function LogsAlertEventTimeline(): JSX.Element {
    const { eventsPage, eventsPageLoading } = useValues(logsAlertEventHistoryLogic)
    const { loadMore } = useActions(logsAlertEventHistoryLogic)

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
        <div className="space-y-3">
            <LemonTable
                columns={columns}
                dataSource={eventsPage.results}
                rowKey="id"
                loading={eventsPageLoading}
                emptyState="No events yet. Transitions and user actions will appear here."
                size="small"
                expandable={{
                    rowExpandable: () => true,
                    expandedRowRender: (event) => <LogsAlertEventDetails event={event} />,
                }}
            />
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

interface EventDescription {
    label: string
    type: LemonTagType
    detail: string | null
}

const CONTROL_PLANE_DESCRIPTIONS: Record<
    Exclude<LogsAlertEventKindEnumApi, typeof LogsAlertEventKindEnumApi.Check>,
    Pick<EventDescription, 'label' | 'type'>
> = {
    [LogsAlertEventKindEnumApi.Reset]: { label: 'Reset', type: 'primary' },
    [LogsAlertEventKindEnumApi.Enable]: { label: 'Enabled', type: 'success' },
    [LogsAlertEventKindEnumApi.Disable]: { label: 'Disabled', type: 'muted' },
    [LogsAlertEventKindEnumApi.Snooze]: { label: 'Snoozed', type: 'highlight' },
    [LogsAlertEventKindEnumApi.Unsnooze]: { label: 'Unsnoozed', type: 'highlight' },
    [LogsAlertEventKindEnumApi.ThresholdChange]: { label: 'Threshold changed', type: 'completion' },
}

function describeEvent(event: LogsAlertEventApi): EventDescription {
    if (event.kind !== LogsAlertEventKindEnumApi.Check) {
        return { ...CONTROL_PLANE_DESCRIPTIONS[event.kind], detail: formatTransition(event) }
    }

    if (event.error_message && event.state_after === 'broken') {
        return {
            label: 'Auto-disabled',
            type: 'caution',
            detail: '5 consecutive errors',
        }
    }
    if (event.error_message) {
        return {
            label: 'Errored',
            type: 'warning',
            detail: truncate(event.error_message, 80),
        }
    }
    if (event.state_before !== 'firing' && event.state_after === 'firing') {
        return {
            label: 'Fired',
            type: 'danger',
            detail:
                event.result_count !== null ? `${event.result_count} logs · threshold breached` : 'threshold breached',
        }
    }
    if (event.state_before === 'firing' && event.state_after !== 'firing') {
        return {
            label: 'Resolved',
            type: 'success',
            detail: event.result_count !== null ? `${event.result_count} logs · back to normal` : 'back to normal',
        }
    }
    return {
        label: 'Check',
        type: 'default',
        detail: event.result_count !== null ? `${event.result_count} logs` : null,
    }
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

function formatTransition(event: LogsAlertEventApi): string | null {
    if (event.state_before === event.state_after) {
        return null
    }
    return `${event.state_before} → ${event.state_after}`
}
