import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconChevronDown, IconLetter } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonInput, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { HogFlowBatchJobApi } from 'products/workflows/frontend/generated/api.schemas'

import { EmailViewerModal } from '../Workflows/EmailViewerModal'
import type { MessageAsset } from '../Workflows/messageAssetsApi'
import { BroadcastEmailPreview } from './BroadcastEmailPreview'
import { BroadcastPerformance } from './BroadcastPerformance'
import { broadcastSentLogic } from './broadcastSentLogic'
import { BroadcastStatusTag } from './BroadcastStatusTag'
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

const LATEST_RUN_LABEL: Record<string, string> = {
    completed: 'Sent',
    waiting: 'Sending, started',
    queued: 'Sending, started',
    active: 'Sending, started',
    failed: 'Last send failed, started',
    cancelled: 'Last send was cancelled, started',
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
        canEditContent,
        duplicating,
        summaryStatus,
    } = useValues(broadcastWizardLogic)
    const { moveToDraft, duplicateBroadcast } = useActions(broadcastWizardLogic)
    const pendingSchedule = broadcast?.schedules?.find((schedule) => schedule.status === 'active')
    const [tab, setTab] = useState<'overview' | 'content' | 'runs'>('overview')

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

    const latestBatchJob = batchJobs[0]
    const latestBatchJobId = latestBatchJob?.id

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
        <div className="@container min-h-full w-full shrink-0 bg-bg-light">
            <div className="mx-auto max-w-6xl space-y-4 px-6 py-6">
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.broadcasts()}>
                    Broadcasts
                </LemonButton>

                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                        <BroadcastStatusTag status={summaryStatus} />
                        <h1 className="m-0 truncate text-2xl font-semibold">{name}</h1>
                    </div>
                    {canMoveToDraft || canEditContent ? (
                        <LemonMenu
                            items={[
                                canMoveToDraft
                                    ? {
                                          label: 'Stop and edit',
                                          onClick: confirmMoveToDraft,
                                          'data-attr': 'broadcast-move-to-draft',
                                      }
                                    : null,
                                canEditContent
                                    ? {
                                          label: 'Send again as a new broadcast',
                                          onClick: duplicateBroadcast,
                                          'data-attr': 'broadcast-send-again',
                                      }
                                    : null,
                            ]}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                sideIcon={<IconChevronDown />}
                                loading={movingToDraft || duplicating}
                                data-attr="broadcast-actions"
                            >
                                Actions
                            </LemonButton>
                        </LemonMenu>
                    ) : null}
                </div>

                <LemonTabs
                    activeKey={tab}
                    onChange={setTab}
                    tabs={[
                        {
                            key: 'overview',
                            'data-attr': 'broadcast-summary-tab-overview',
                            label: 'Overview',
                            content: (
                                <div className="flex flex-col gap-4">
                                    <div className="grid grid-cols-1 gap-4 rounded-lg border border-border bg-surface-primary p-4 @2xl:grid-cols-3">
                                        <SummaryRow label="Audience">
                                            {audienceProperties.length > 0 ? (
                                                <PropertyFiltersDisplay filters={audienceProperties} />
                                            ) : (
                                                <span className="text-muted">Everyone</span>
                                            )}
                                        </SummaryRow>
                                        <SummaryRow label="Schedule">
                                            {pendingSchedule ? (
                                                <div className="flex flex-col gap-0.5">
                                                    <span>{scheduleSummary}</span>
                                                    {pendingSchedule.next_run_at ? (
                                                        <span className="text-xs text-muted">
                                                            Next send <TZLabel time={pendingSchedule.next_run_at} />
                                                        </span>
                                                    ) : null}
                                                </div>
                                            ) : latestBatchJob ? (
                                                <span>
                                                    {LATEST_RUN_LABEL[latestBatchJob.status ?? 'waiting'] ?? 'Last run'}{' '}
                                                    <TZLabel time={latestBatchJob.created_at} />
                                                </span>
                                            ) : (
                                                <span>{scheduleSummary}</span>
                                            )}
                                        </SummaryRow>
                                        <SummaryRow label="Subject">
                                            {email.subject || <span className="text-muted">No subject</span>}
                                        </SummaryRow>
                                    </div>
                                    <div className="flex flex-col gap-2">
                                        <h2 className="m-0 text-base font-semibold">
                                            {latestBatchJobId ? 'Performance (latest send)' : 'Performance'}
                                        </h2>
                                        {latestBatchJob ? (
                                            <BroadcastPerformance
                                                runId={latestBatchJob.id}
                                                runStartedAt={latestBatchJob.created_at}
                                            />
                                        ) : (
                                            <span className="text-muted">
                                                Numbers show up here once the first send goes out.
                                            </span>
                                        )}
                                    </div>
                                </div>
                            ),
                        },
                        {
                            key: 'content',
                            'data-attr': 'broadcast-summary-tab-content',
                            label: 'Content',
                            content: (
                                <BroadcastEmailPreview intro="Preview the email for anyone in the audience, or send yourself a test." />
                            ),
                        },
                        {
                            key: 'runs',
                            'data-attr': 'broadcast-summary-tab-runs',
                            label: 'Runs',
                            content: (
                                <RunsTable
                                    workflowId={broadcastId ?? ''}
                                    batchJobs={batchJobs}
                                    batchJobsLoading={batchJobsLoading}
                                    columns={batchJobColumns}
                                />
                            ),
                        },
                    ]}
                />
            </div>
        </div>
    )
}

function SummaryRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
            {children}
        </div>
    )
}
