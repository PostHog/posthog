import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSelect, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { LogsAlertCheckApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertingLogic } from './logsAlertingLogic'

const OUTCOME_OPTIONS = [
    { value: 'all', label: 'All' },
    { value: 'breached', label: 'Breached' },
    { value: 'ok', label: 'OK' },
    { value: 'errored', label: 'Errored' },
]

const columns: LemonTableColumns<LogsAlertCheckApi> = [
    {
        title: 'Time',
        dataIndex: 'created_at',
        render: (_, check) => <TZLabel time={check.created_at} timestampStyle="absolute" />,
    },
    {
        title: 'Count',
        dataIndex: 'result_count',
        render: (_, check) => <span className="font-medium">{check.result_count ?? '—'}</span>,
    },
    {
        title: 'Breached',
        dataIndex: 'threshold_breached',
        render: (_, check) => (
            <LemonTag type={check.threshold_breached ? 'danger' : 'success'} size="small">
                {check.threshold_breached ? 'Yes' : 'No'}
            </LemonTag>
        ),
    },
    {
        title: 'Transition',
        render: (_, check) =>
            check.state_before !== check.state_after ? (
                <span className="text-xs font-medium">
                    {check.state_before} → {check.state_after}
                </span>
            ) : (
                <span className="text-xs text-secondary">{check.state_after}</span>
            ),
    },
    {
        title: 'Query time',
        dataIndex: 'query_duration_ms',
        render: (_, check) =>
            check.query_duration_ms != null ? (
                <span className="text-xs text-secondary">{check.query_duration_ms}ms</span>
            ) : (
                '—'
            ),
    },
    {
        title: 'Error',
        dataIndex: 'error_message',
        render: (_, check) =>
            check.error_message ? (
                <span className="text-xs text-danger truncate max-w-[200px] block" title={check.error_message}>
                    {check.error_message}
                </span>
            ) : null,
    },
]

export function LogsAlertCheckHistory(): JSX.Element {
    const {
        checkHistoryAlert,
        checkHistory,
        checkHistoryLoading,
        checkHistoryOutcome,
        checkHistoryNext,
        checkHistoryPrevious,
    } = useValues(logsAlertingLogic)
    const { closeCheckHistory, setCheckHistoryOutcome, loadCheckHistoryPage } = useActions(logsAlertingLogic)

    return (
        <LemonModal
            isOpen={checkHistoryAlert !== null}
            onClose={closeCheckHistory}
            title={`Check history: ${checkHistoryAlert?.name ?? ''}`}
            width={860}
        >
            <div className="p-4 space-y-3">
                <div className="flex gap-2 items-center justify-between">
                    <LemonSelect
                        size="small"
                        value={checkHistoryOutcome}
                        onChange={setCheckHistoryOutcome}
                        options={OUTCOME_OPTIONS}
                    />
                    <div className="flex gap-1">
                        {checkHistoryPrevious && (
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => loadCheckHistoryPage(checkHistoryPrevious)}
                            >
                                Previous
                            </LemonButton>
                        )}
                        {checkHistoryNext && (
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => loadCheckHistoryPage(checkHistoryNext)}
                            >
                                Next
                            </LemonButton>
                        )}
                    </div>
                </div>
                <LemonTable
                    columns={columns}
                    dataSource={checkHistory.results}
                    loading={checkHistoryLoading}
                    rowKey="id"
                    size="small"
                    emptyState="No checks recorded yet."
                />
            </div>
        </LemonModal>
    )
}
