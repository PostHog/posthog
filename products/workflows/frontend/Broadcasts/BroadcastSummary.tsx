import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft, IconLetter } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonInput, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { HogFlowBatchJobApi } from 'products/workflows/frontend/generated/api.schemas'

import { EmailMetricsSummary } from '../Workflows/EmailMetricsSummary'
import { EmailViewerModal } from '../Workflows/EmailViewerModal'
import type { MessageAsset } from '../Workflows/messageAssetsApi'
import { broadcastSentLogic } from './broadcastSentLogic'
import { broadcastWizardLogic } from './broadcastWizardLogic'

const BATCH_JOB_STATUS_TAG: Record<string, LemonTagType> = {
    waiting: 'default',
    queued: 'warning',
    active: 'warning',
    completed: 'success',
    cancelled: 'muted',
    failed: 'danger',
}

/**
 * The recipients of one run. Each run binds its own broadcastSentLogic (keyed on the run id), so
 * expanding a second run loads that run's sends instead of replacing the first one's.
 */
function RunRecipients({
    workflowId,
    runId,
    runCreatedAt,
}: {
    workflowId: string
    runId: string
    runCreatedAt: string
}): JSX.Element {
    return (
        <div className="bg-surface-secondary border-t px-4 py-3 w-0 min-w-full">
            <BindLogic logic={broadcastSentLogic} props={{ id: workflowId || 'new', parentRunId: runId, runCreatedAt }}>
                <RunRecipientsTable workflowId={workflowId} />
            </BindLogic>
        </div>
    )
}

function RunRecipientsTable({ workflowId }: { workflowId: string }): JSX.Element {
    const {
        sends,
        sendsLoading,
        sendsFailed,
        selectedSend,
        recipientCount,
        recipientSearch,
        hasMoreRecipients,
        runPastRetention,
    } = useValues(broadcastSentLogic)
    const { loadSends, loadMoreSends, selectInvocation, setRecipientSearch } = useActions(broadcastSentLogic)

    useEffect(() => {
        loadSends()
    }, [loadSends])

    const noSendsMessage = runPastRetention
        ? "Recipient details are kept for 30 days after sending, so this run's list is no longer available."
        : 'No sends recorded for this run yet.'

    const columns: LemonTableColumns<MessageAsset> = [
        {
            title: 'Sent',
            key: 'sent_at',
            render: (_, row) => <TZLabel time={row.sent_at} />,
        },
        {
            title: 'Subject',
            key: 'subject',
            render: (_, row) => <span className="wrap-anywhere">{row.subject || '-'}</span>,
        },
        {
            title: 'Recipient',
            key: 'recipient',
            // An address has no break points, so without break-all its full length would widen the
            // table past the panel and push the View email button out of sight.
            render: (_, row) => <span className="font-mono text-xs break-all">{row.recipient}</span>,
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, row) => (
                <div className="flex justify-end whitespace-nowrap">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconLetter />}
                        onClick={() => selectInvocation(row.invocation_id)}
                        data-attr="broadcast-view-recipient-email"
                    >
                        View email
                    </LemonButton>
                </div>
            ),
        },
    ]

    if (!sendsLoading && recipientCount === 0 && !recipientSearch) {
        return (
            <span className="text-sm text-muted">
                {sendsFailed ? "Couldn't load recipients. Refresh the page to try again." : noSendsMessage}
            </span>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold whitespace-nowrap">
                    {sendsFailed
                        ? "Couldn't load recipients"
                        : sendsLoading && recipientCount === 0
                          ? 'Loading recipients'
                          : `${humanFriendlyNumber(recipientCount)}${hasMoreRecipients ? '+' : ''} ${
                                recipientCount === 1 ? 'recipient' : 'recipients'
                            }${recipientSearch ? ' matching' : ''}`}
                </span>
                <LemonDivider vertical />
                <LemonInput
                    size="small"
                    type="search"
                    placeholder="Search by email or subject"
                    value={recipientSearch}
                    onChange={setRecipientSearch}
                    className="w-full min-w-40 max-w-64 flex-1"
                    data-attr="broadcast-sent-search"
                />
            </div>
            {/* Each day of sends expires separately. A run that sent over several days still lists its later
                days after its first day expires, so a non-empty list can be incomplete. */}
            {runPastRetention && !sendsFailed ? (
                <span className="text-xs text-muted">
                    Recipient details are kept for 30 days after sending, so this list may not include everyone this run
                    reached.
                </span>
            ) : null}
            <LemonTable
                // The loader keeps the previous rows on failure, and they no longer match the search.
                dataSource={sendsFailed ? [] : sends}
                loading={sendsLoading}
                rowKey="invocation_id"
                columns={columns}
                nouns={['recipient', 'recipients']}
                emptyState={
                    sendsFailed
                        ? "Couldn't load recipients. Change the search to try again, or refresh the page."
                        : recipientSearch
                          ? 'No recipients match. Clear the search to see everyone.'
                          : noSendsMessage
                }
            />
            {hasMoreRecipients && !sendsFailed ? (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={sendsLoading}
                        onClick={loadMoreSends}
                        data-attr="broadcast-sent-load-more"
                    >
                        Load more recipients
                    </LemonButton>
                </div>
            ) : null}
            {selectedSend ? (
                <EmailViewerModal
                    workflowId={workflowId}
                    invocationId={selectedSend.invocation_id}
                    actionId={selectedSend.action_id}
                    isOpen
                    onClose={() => selectInvocation(null)}
                    title={`Email sent to ${selectedSend.recipient}`}
                    description={selectedSend.subject}
                />
            ) : null}
        </div>
    )
}

function RunsTable({
    workflowId,
    batchJobs,
    batchJobsLoading,
    columns,
}: {
    workflowId: string
    batchJobs: HogFlowBatchJobApi[]
    batchJobsLoading: boolean
    columns: LemonTableColumns<HogFlowBatchJobApi>
}): JSX.Element {
    const { expandedRunIds } = useValues(broadcastWizardLogic)
    const { expandRun, collapseRun } = useActions(broadcastWizardLogic)

    return (
        <LemonTable
            dataSource={batchJobs}
            loading={batchJobsLoading}
            rowKey="id"
            columns={columns}
            nouns={['run', 'runs']}
            expandable={{
                expandedRowRender: (job) => (
                    <RunRecipients workflowId={workflowId} runId={job.id} runCreatedAt={job.created_at} />
                ),
                rowExpandable: (job) => !!job.id,
                // A table inside a table runs out of room first. Dropping the indent cell gives the
                // recipients back the width the toggle column would otherwise take.
                noIndent: true,
                isRowExpanded: (job) => (expandedRunIds.includes(job.id) ? 1 : 0),
                onRowExpand: (job) => expandRun(job.id),
                onRowCollapse: (job) => collapseRun(job.id),
            }}
            emptyState="No runs yet. Scheduled broadcasts appear here after they send."
        />
    )
}

export function BroadcastSummary(): JSX.Element {
    const {
        broadcast,
        broadcastId,
        name,
        audienceProperties,
        email,
        scheduleSummary,
        batchJobs,
        batchJobsLoading,
        canMoveToDraft,
        movingToDraft,
    } = useValues(broadcastWizardLogic)
    const { moveToDraft } = useActions(broadcastWizardLogic)

    const confirmMoveToDraft = (): void => {
        LemonDialog.open({
            title: 'Stop this broadcast and edit it?',
            description:
                'The scheduled send stops and the broadcast goes back to draft. Nothing sends until you launch it again.',
            primaryButton: {
                children: 'Stop and edit',
                onClick: moveToDraft,
                'data-attr': 'broadcast-move-to-draft-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    // Email metrics from a batch send are attributed to the batch job, not the flow (see
    // `parentRunId ?? functionId` in the plugin server's email service), so a flow-scoped query
    // returns zeros for every broadcast. Key the logic by the run so it remounts once runs load.
    const latestBatchJob = batchJobs[0]
    const latestBatchJobId = latestBatchJob?.id
    const metricsSourceId = latestBatchJobId ?? broadcastId
    const logicKey = `broadcast-${metricsSourceId}`
    // Mounting with force params here pins the metrics query to this run; EmailMetricsSummary
    // reads the same keyed logic below. The date window follows the run rather than a fixed
    // lookback, so a send older than 30 days still shows its counts.
    useValues(
        appMetricsLogic({
            logicKey,
            loadOnMount: true,
            loadOnChanges: true,
            forceParams: {
                appSource: 'hog_flow',
                appSourceId: metricsSourceId ?? undefined,
                breakdownBy: 'metric_name',
                dateFrom: latestBatchJob ? dayjs(latestBatchJob.created_at).subtract(1, 'hour').toISOString() : '-30d',
                dateTo: latestBatchJob ? dayjs().add(1, 'hour').toISOString() : undefined,
                interval: 'day',
            },
        })
    )

    const batchJobColumns: LemonTableColumns<HogFlowBatchJobApi> = [
        {
            title: 'Started',
            key: 'created_at',
            render: (_, job) => <TZLabel time={job.created_at} />,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, job) => (
                <LemonTag type={BATCH_JOB_STATUS_TAG[job.status ?? 'waiting'] ?? 'default'}>
                    {capitalizeFirstLetter(job.status ?? 'waiting')}
                </LemonTag>
            ),
        },
        {
            title: 'Started by',
            key: 'created_by',
            render: (_, job) => <span>{job.created_by?.first_name || job.created_by?.email || 'Schedule'}</span>,
        },
    ]

    return (
        <div className="min-h-full w-full shrink-0 bg-bg-light">
            <div className="mx-auto max-w-4xl space-y-5 px-6 py-6">
                <div className="flex items-center justify-between gap-2">
                    <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.broadcasts()}>
                        Broadcasts
                    </LemonButton>
                    {canMoveToDraft ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={confirmMoveToDraft}
                            loading={movingToDraft}
                            data-attr="broadcast-move-to-draft"
                        >
                            Stop and edit
                        </LemonButton>
                    ) : null}
                </div>

                <div className="flex items-center gap-2">
                    <h1 className="m-0 text-2xl font-semibold">{name}</h1>
                    <LemonTag type={broadcast?.status === 'active' ? 'success' : 'default'}>
                        {capitalizeFirstLetter(broadcast?.status ?? 'draft')}
                    </LemonTag>
                </div>

                <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-primary p-4">
                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Audience</span>
                        {audienceProperties.length > 0 ? (
                            <PropertyFiltersDisplay filters={audienceProperties} />
                        ) : (
                            <span className="text-muted">Everyone</span>
                        )}
                    </div>
                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Schedule</span>
                        <span>{scheduleSummary}</span>
                    </div>
                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Email subject</span>
                        <span>{email.subject || 'No subject'}</span>
                    </div>
                </div>

                <div className="flex flex-col gap-2">
                    <h2 className="m-0 text-lg font-semibold">
                        {latestBatchJobId ? 'Performance (latest send)' : 'Performance (last 30 days)'}
                    </h2>
                    <EmailMetricsSummary logicKey={logicKey} compact />
                </div>

                <div className="flex flex-col gap-2">
                    <h2 className="m-0 text-lg font-semibold">Runs</h2>
                    <RunsTable
                        workflowId={broadcastId ?? ''}
                        batchJobs={batchJobs}
                        batchJobsLoading={batchJobsLoading}
                        columns={batchJobColumns}
                    />
                </div>
            </div>
        </div>
    )
}
