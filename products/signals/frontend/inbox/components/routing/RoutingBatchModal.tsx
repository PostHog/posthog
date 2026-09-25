import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonTable, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxRoutingLogic } from '../../logics/inboxRoutingLogic'

export function RoutingBatchModal({ projectId }: { projectId: string }): JSX.Element {
    const logic = inboxRoutingLogic({ projectId })
    const { catalogue, batch, batchVisible, batchLoading, batchReports, batchReportsLoading, reportsOffset, error } =
        useValues(logic)
    const { closeBatch, applyBatch, undoBatch, retryBatch, loadBatch, loadBatchReports } = useActions(logic)
    const domain = catalogue?.domains.find((domain) => domain.id === batch?.domain_id)
    const active = batch && ['pending', 'running', 'undoing'].includes(batch.status)
    const canUndo = batch && ['pending', 'running', 'complete', 'failed'].includes(batch.status)

    return (
        <LemonModal
            isOpen={batchVisible}
            onClose={closeBatch}
            title={domain ? `Your routing for ${domain.name}` : 'Your routing'}
            width={640}
        >
            <div className="flex flex-col gap-3">
                {error && <LemonBanner type="error">{error}</LemonBanner>}
                {!batch ? (
                    batchLoading && <Spinner />
                ) : (
                    <>
                        {batch.status === 'preview' ? (
                            <>
                                <p>
                                    This removes your suggestions from the matching reports below and remembers the
                                    domain rule for future routing. Other people can still find and act on these
                                    reports.
                                </p>
                                <LemonBanner type="info">
                                    Work you have claimed stays assigned to you. Reports edited after this preview may
                                    be skipped. Uncertain domain matches are not included.
                                </LemonBanner>
                            </>
                        ) : (
                            <>
                                <p>{`Status: ${batch.status}. Removed from ${batch.changed} of ${batch.total} reports. ${batch.skipped_claims} kept because you own work; ${batch.skipped_changes} skipped after other changes.`}</p>
                                {active && (
                                    <p className="m-0">
                                        Your rule takes effect immediately. Cleanup continues if you close this window.
                                    </p>
                                )}
                                {batch.status === 'undone' && (
                                    <p>Undo finished. Newer report edits and routing rules were preserved.</p>
                                )}
                            </>
                        )}
                        <LemonTable
                            loading={batchReportsLoading}
                            dataSource={batchReports?.results ?? []}
                            rowKey="report_id"
                            emptyState="No matching suggestions. You can still save the rule for future reports."
                            columns={[
                                {
                                    title: 'Report',
                                    dataIndex: 'title',
                                    render: (_, row) => (
                                        <Link to={urls.inboxReport('reports', row.report_id)}>
                                            {row.title || 'Untitled report'}
                                        </Link>
                                    ),
                                },
                                {
                                    title: 'Result',
                                    render: (_, row) => (row.has_active_claim ? 'Keep active work' : row.status),
                                },
                            ]}
                        />
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                onClick={() =>
                                    loadBatchReports({ batchId: batch.id, offset: Math.max(0, reportsOffset - 20) })
                                }
                                disabledReason={
                                    reportsOffset === 0 || batchReportsLoading ? 'First page or loading' : undefined
                                }
                            >
                                Previous
                            </LemonButton>
                            <LemonButton
                                size="small"
                                onClick={() => loadBatchReports({ batchId: batch.id, offset: reportsOffset + 20 })}
                                disabledReason={
                                    !batchReports?.next || batchReportsLoading ? 'Last page or loading' : undefined
                                }
                            >
                                Next
                            </LemonButton>
                            <LemonButton
                                size="small"
                                onClick={() => {
                                    loadBatch({ batchId: batch.id })
                                    loadBatchReports({ batchId: batch.id, offset: reportsOffset })
                                }}
                                loading={batchLoading}
                            >
                                Refresh
                            </LemonButton>
                        </div>
                        <div className="flex flex-wrap justify-end gap-2">
                            <LemonButton type="secondary" onClick={closeBatch}>
                                Close
                            </LemonButton>
                            {batch.status === 'preview' && (
                                <LemonButton
                                    type="primary"
                                    onClick={() => applyBatch({ batchId: batch.id })}
                                    loading={batchLoading}
                                    disabledReason={
                                        !batchReports || batchReportsLoading
                                            ? 'Review the affected reports first'
                                            : undefined
                                    }
                                    data-attr="inbox-routing-bulk-apply"
                                >
                                    Remove me and remember
                                </LemonButton>
                            )}
                            {batch.status === 'failed' && batch.error === 'cleanup_failed' && (
                                <LemonButton
                                    type="primary"
                                    onClick={() => retryBatch({ batchId: batch.id })}
                                    loading={batchLoading}
                                    data-attr="inbox-routing-bulk-retry"
                                >
                                    Retry cleanup
                                </LemonButton>
                            )}
                            {canUndo && (
                                <LemonButton
                                    type="secondary"
                                    onClick={() => undoBatch({ batchId: batch.id })}
                                    loading={batchLoading}
                                    data-attr="inbox-routing-bulk-undo"
                                >
                                    Undo this operation
                                </LemonButton>
                            )}
                        </div>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
