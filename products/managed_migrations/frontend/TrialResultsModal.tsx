import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { managedMigrationLogic } from './managedMigrationLogic'
import type { TrialRecord, TrialSummary } from './types'

function SummaryStat({ label, value }: { label: string; value: number }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-xs text-muted">{label}</span>
            <span className="text-lg font-semibold">{value.toLocaleString()}</span>
        </div>
    )
}

function JsonBlock({ title, value }: { title: string; value: unknown }): JSX.Element {
    return (
        <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold text-muted mb-1">{title}</div>
            <pre className="text-xs bg-bg-light border rounded p-2 overflow-auto max-h-80">
                {JSON.stringify(value, null, 2)}
            </pre>
        </div>
    )
}

function recordEventName(record: TrialRecord): string {
    if (record.outputs.length > 0) {
        return record.outputs.map((output) => output.event).join(', ')
    }
    const source = record.source as Record<string, unknown> | null
    const name = source?.['event'] ?? source?.['event_type']
    return typeof name === 'string' ? name : '—'
}

export function TrialResultsModal(): JSX.Element {
    const { trialResultsId, trialRecords, trialRecordsLoading } = useValues(managedMigrationLogic)
    const { closeTrialResults, loadTrialRecordsPage } = useActions(managedMigrationLogic)

    const summary = (trialRecords?.summary ?? null) as TrialSummary | null
    const records = (trialRecords?.records ?? []) as TrialRecord[]
    const page = trialRecords?.page ?? 0
    const totalPages = trialRecords?.total_pages ?? 0
    const errorEntries = Object.entries(summary?.error_counts ?? {})

    return (
        <LemonModal
            isOpen={!!trialResultsId}
            onClose={closeTrialResults}
            title="Trial run results"
            description="Each source record is shown with the event(s) it would produce on a real import, or the reason it failed. No events were ingested."
            width={960}
        >
            <div className="space-y-4">
                {summary && (
                    <div className="flex gap-8">
                        <SummaryStat label="Records processed" value={trialRecords?.total_records ?? 0} />
                        <SummaryStat label="Events to import" value={summary.output_events} />
                        <SummaryStat label="Failed" value={summary.dropped_records} />
                        <SummaryStat label="Skipped" value={summary.skipped_records} />
                    </div>
                )}

                {errorEntries.length > 0 && (
                    <LemonBanner type="warning">
                        <div className="font-semibold mb-1">Some records can't be imported</div>
                        <div className="mb-1">
                            These errors are not retriable. A full import will pause when it reaches the first failing
                            record, and stay paused until the source data is fixed.
                        </div>
                        <ul className="list-disc pl-4">
                            {errorEntries.map(([message, count]) => (
                                <li key={message}>
                                    {message} <span className="text-muted">({count.toLocaleString()})</span>
                                </li>
                            ))}
                        </ul>
                    </LemonBanner>
                )}

                <LemonTable
                    dataSource={records}
                    loading={trialRecordsLoading}
                    rowKey="seq"
                    columns={[
                        {
                            title: '#',
                            key: 'seq',
                            width: 60,
                            render: (_: any, record: TrialRecord) => <span className="text-muted">{record.seq}</span>,
                        },
                        {
                            title: 'Event',
                            key: 'event',
                            render: (_: any, record: TrialRecord) => recordEventName(record),
                        },
                        {
                            title: 'Result',
                            key: 'result',
                            render: (_: any, record: TrialRecord) => {
                                if (record.error) {
                                    return <LemonTag type="danger">Failed</LemonTag>
                                }
                                if (record.outputs.length === 0) {
                                    return <LemonTag type="muted">Skipped</LemonTag>
                                }
                                return (
                                    <LemonTag type="success">
                                        {record.outputs.length === 1 ? '1 event' : `${record.outputs.length} events`}
                                    </LemonTag>
                                )
                            },
                        },
                        {
                            title: 'Details',
                            key: 'details',
                            render: (_: any, record: TrialRecord) => record.error ?? null,
                        },
                    ]}
                    expandable={{
                        expandedRowRender: (record: TrialRecord) => (
                            <div className="flex gap-4 p-2">
                                <JsonBlock title="Source event" value={record.source} />
                                <JsonBlock
                                    title={record.error ? 'Error' : 'Imported event(s)'}
                                    value={record.error ?? record.outputs}
                                />
                            </div>
                        ),
                    }}
                    emptyState="No records in this trial run."
                />

                {totalPages > 1 && (
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            disabledReason={page === 0 ? 'Already on the first page' : undefined}
                            loading={trialRecordsLoading}
                            onClick={() => loadTrialRecordsPage({ page: page - 1 })}
                        >
                            Previous
                        </LemonButton>
                        <span className="text-muted text-sm">
                            Page {page + 1} of {totalPages}
                        </span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            disabledReason={page >= totalPages - 1 ? 'Already on the last page' : undefined}
                            loading={trialRecordsLoading}
                            onClick={() => loadTrialRecordsPage({ page: page + 1 })}
                        >
                            Next
                        </LemonButton>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
