import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft, IconCheck, IconLetter, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { HogFlowBatchJobApi } from 'products/workflows/frontend/generated/api.schemas'

import { EmailMetricsSummary } from '../Workflows/EmailMetricsSummary'
import { EmailViewerModal } from '../Workflows/EmailViewerModal'
import { type MessageAsset, getMessageAssetContentUrl } from '../Workflows/messageAssetsApi'
import { broadcastSentLogic } from './broadcastSentLogic'
import { broadcastsLogic } from './broadcastsLogic'
import { BroadcastSummaryTab, broadcastWizardLogic } from './broadcastWizardLogic'

const BATCH_JOB_STATUS_TAG: Record<string, LemonTagType> = {
    waiting: 'default',
    queued: 'warning',
    active: 'warning',
    completed: 'success',
    cancelled: 'muted',
    failed: 'danger',
}

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-primary p-4">
            <h3 className="m-0 text-base font-semibold">{title}</h3>
            {children}
        </div>
    )
}

function OverviewTab({ logicKey, hasRun }: { logicKey: string; hasRun: boolean }): JSX.Element {
    return (
        <Section title={hasRun ? 'Metrics for the latest send' : 'Metrics for the last 30 days'}>
            <EmailMetricsSummary logicKey={logicKey} />
        </Section>
    )
}

const TEMPLATE_OPTION = '__template__'

function ContentTab({ workflowId }: { workflowId: string }): JSX.Element {
    const { email } = useValues(broadcastWizardLogic)
    const { sends, sendsLoading, previewSend } = useValues(broadcastSentLogic)
    const { loadSends, setPreviewSend, setRecipientSearch } = useActions(broadcastSentLogic)

    useEffect(() => {
        loadSends()
    }, [loadSends])

    return (
        <div className="flex flex-col gap-4">
            <Section title="Email">
                <div className="grid grid-cols-[max-content_1fr] items-center gap-x-4 gap-y-2 text-sm">
                    <span className="text-muted">To</span>
                    {sends.length > 0 ? (
                        <div className="flex items-center gap-2">
                            <div className="min-w-80" data-attr="broadcast-content-recipient-picker">
                                <LemonInputSelect
                                    mode="single"
                                    size="small"
                                    value={previewSend ? [previewSend.invocation_id] : [TEMPLATE_OPTION]}
                                    onChange={(values) => {
                                        // Typing clears the single-select's value; keep the current preview
                                        // on screen until a recipient is actually picked.
                                        if (!values[0]) {
                                            return
                                        }
                                        setPreviewSend(sends.find((send) => send.invocation_id === values[0]) ?? null)
                                    }}
                                    onInputChange={setRecipientSearch}
                                    loading={sendsLoading}
                                    // The options are already the server's answer to this search, and the
                                    // built-in fuzzy filter drops valid matches on strings like "+9@".
                                    disableFiltering
                                    placeholder="Search recipients"
                                    options={[
                                        { key: TEMPLATE_OPTION, label: 'Template (variables unrendered)' },
                                        ...sends.map((send) => ({ key: send.invocation_id, label: send.recipient })),
                                    ]}
                                />
                            </div>
                            <span className="text-xs text-muted">
                                {previewSend
                                    ? 'Showing the email this person was sent.'
                                    : 'Showing the stored template.'}
                            </span>
                        </div>
                    ) : (
                        <span className="font-mono text-xs">{email.to?.email || '-'}</span>
                    )}
                    <span className="text-muted">Subject</span>
                    <span>{previewSend?.subject || email.subject || 'No subject'}</span>
                    {!previewSend && email.preheader ? (
                        <>
                            <span className="text-muted">Preheader</span>
                            <span>{email.preheader}</span>
                        </>
                    ) : null}
                </div>
            </Section>
            <Section title="Preview">
                {previewSend ? (
                    <>
                        <p className="m-0 text-xs text-muted">
                            The email as it was delivered to {previewSend.recipient}, rendered from what we stored at
                            send time. Pick another recipient above to see theirs.
                        </p>
                        <iframe
                            title="Rendered email"
                            sandbox=""
                            src={getMessageAssetContentUrl(
                                workflowId,
                                previewSend.invocation_id,
                                previewSend.action_id
                            )}
                            className="h-[32rem] w-full rounded border border-border bg-white"
                        />
                    </>
                ) : (
                    <>
                        <p className="m-0 text-xs text-muted">
                            The email as stored on the broadcast, with its variables unrendered.
                            {sends.length > 0 ? ' Pick a recipient above to see a delivered copy.' : ''}
                        </p>
                        {email.html ? (
                            <iframe
                                srcDoc={email.html}
                                sandbox=""
                                title="Broadcast email preview"
                                className="h-[32rem] w-full rounded border border-border bg-white"
                            />
                        ) : (
                            <span className="text-muted">This broadcast has no email content.</span>
                        )}
                    </>
                )}
            </Section>
        </div>
    )
}

const SEND_STATUS_TAG: Record<string, LemonTagType> = {
    sent: 'default',
    delivered: 'success',
    opened: 'success',
    clicked: 'success',
    bounced: 'danger',
    failed: 'danger',
    unsubscribed: 'warning',
    spam: 'danger',
}

function SentTab({ workflowId }: { workflowId: string }): JSX.Element {
    const {
        filteredSends,
        sendsLoading,
        sendsFailed,
        statusFilter,
        statuses,
        selectedSend,
        recipientCount,
        recipientSearch,
        hasMoreRecipients,
    } = useValues(broadcastSentLogic)
    const { loadSends, setStatusFilter, selectInvocation, setRecipientSearch } = useActions(broadcastSentLogic)

    useEffect(() => {
        loadSends()
    }, [loadSends])

    const columns: LemonTableColumns<MessageAsset> = [
        {
            title: 'Sent',
            key: 'sent_at',
            render: (_, row) => <TZLabel time={row.sent_at} />,
        },
        {
            title: 'Subject',
            key: 'subject',
            render: (_, row) => <span>{row.subject || '-'}</span>,
        },
        {
            title: 'Recipient',
            key: 'recipient',
            render: (_, row) => <span className="font-mono text-xs">{row.recipient}</span>,
        },
        {
            title: 'Status',
            key: 'status',
            width: 0,
            render: (_, row) => (
                <LemonTag type={SEND_STATUS_TAG[row.status] ?? 'default'}>
                    {capitalizeFirstLetter(row.status || 'unknown')}
                </LemonTag>
            ),
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

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">
                    {sendsLoading && recipientCount === 0
                        ? 'Loading recipients'
                        : `${humanFriendlyNumber(recipientCount)}${hasMoreRecipients ? '+' : ''} ${
                              recipientCount === 1 ? 'recipient' : 'recipients'
                          }${recipientSearch ? ' matching' : ''}`}
                </span>
                {statusFilter ? (
                    <span className="text-sm text-muted">· showing {humanFriendlyNumber(filteredSends.length)}</span>
                ) : null}
                <LemonDivider vertical />
                <LemonInput
                    size="small"
                    type="search"
                    placeholder="Search by email or subject"
                    value={recipientSearch}
                    onChange={setRecipientSearch}
                    className="w-64"
                    data-attr="broadcast-sent-search"
                />
                <span className="text-sm text-muted">Filter by</span>
                <LemonSelect
                    size="small"
                    value={statusFilter}
                    onChange={(value) => setStatusFilter(value)}
                    data-attr="broadcast-sent-status-filter"
                    options={[
                        { value: null, label: 'All statuses' },
                        ...statuses.map((status) => ({ value: status, label: capitalizeFirstLetter(status) })),
                    ]}
                />
            </div>
            <LemonTable
                dataSource={filteredSends}
                loading={sendsLoading}
                rowKey="invocation_id"
                columns={columns}
                nouns={['recipient', 'recipients']}
                emptyState={
                    sendsFailed
                        ? "Couldn't load recipients. Refresh the page to try again."
                        : 'No sends recorded for this run yet.'
                }
            />
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

function RecipientsTab({ batchJobs }: { batchJobs: HogFlowBatchJobApi[] }): JSX.Element {
    const { audienceProperties, scheduleSummary, conversion, goalEnabled, emailRateLimit } =
        useValues(broadcastWizardLogic)
    const { recipientCount } = useValues(broadcastSentLogic)
    const { loadSends } = useActions(broadcastSentLogic)
    const firstRun = batchJobs[batchJobs.length - 1]

    useEffect(() => {
        loadSends()
    }, [loadSends])

    return (
        <div className="flex flex-col gap-4">
            <Section title="Recipients">
                {recipientCount > 0 ? (
                    <div className="text-2xl font-semibold">
                        {humanFriendlyNumber(recipientCount)} {recipientCount === 1 ? 'person' : 'people'}
                    </div>
                ) : null}
                <p className="m-0 text-sm text-muted">
                    {recipientCount > 0 ? 'Matching:' : 'This broadcast goes to people matching:'}
                </p>
                {audienceProperties.length > 0 ? (
                    <PropertyFiltersDisplay filters={audienceProperties} />
                ) : (
                    <span>Everyone</span>
                )}
            </Section>

            <Section title="Tracking">
                <div className="flex items-center gap-2 text-sm">
                    <IconCheck className="text-success" />
                    <span>Open and click tracking are on</span>
                </div>
                <div className="flex items-center gap-2 text-sm">
                    {goalEnabled ? <IconCheck className="text-success" /> : <IconX className="text-muted" />}
                    <span>
                        {goalEnabled
                            ? `Conversion counted within ${conversion.window_minutes ?? 0} minutes`
                            : 'Not tracking a conversion goal'}
                    </span>
                </div>
            </Section>

            <Section title="Send options">
                <div className="text-sm">{scheduleSummary}</div>
                {firstRun ? (
                    <div className="text-sm text-muted">
                        First run started <TZLabel time={firstRun.created_at} />.
                    </div>
                ) : null}
                <div className="text-sm text-muted">
                    {emailRateLimit
                        ? `Send rate limited to ${emailRateLimit.count} emails per ${emailRateLimit.period}.`
                        : 'No send rate limit was set, so the send went out as fast as possible.'}
                </div>
            </Section>
        </div>
    )
}

export function BroadcastSummary(): JSX.Element {
    const { broadcast, broadcastId, name, batchJobs, batchJobsLoading, summaryTab } = useValues(broadcastWizardLogic)
    const { setSummaryTab } = useActions(broadcastWizardLogic)
    const { archiveBroadcast, restoreBroadcast, duplicateBroadcast, deleteBroadcast } = useActions(broadcastsLogic)

    // Email metrics from a batch send are attributed to the batch job, not the flow (see
    // `parentRunId ?? functionId` in the plugin server's email service), so a flow-scoped query
    // returns zeros for every broadcast. Key the logic by the run so it remounts once runs load.
    const latestBatchJob = batchJobs[0]
    const latestBatchJobId = latestBatchJob?.id
    const metricsSourceId = latestBatchJobId ?? broadcastId
    const logicKey = `broadcast-${metricsSourceId}`
    // Mounting with force params here pins the metrics query to this run; EmailMetricsSummary
    // reads the same keyed logic below. The date window follows the run rather than a fixed
    // lookback, so a send older than 30 days still shows its counts. Hourly buckets for a run,
    // because a broadcast lands within minutes and daily buckets flatten it to one bar.
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
                interval: latestBatchJob ? 'hour' : 'day',
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
            <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">
                <div className="flex items-center justify-between">
                    <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.broadcasts()}>
                        Broadcasts
                    </LemonButton>
                    {broadcastId && broadcast && (
                        <div className="flex items-center gap-2">
                            <More
                                overlay={
                                    <>
                                        <LemonButton
                                            fullWidth
                                            data-attr="broadcast-detail-duplicate"
                                            onClick={() => duplicateBroadcast(broadcast)}
                                        >
                                            Duplicate
                                        </LemonButton>
                                        <LemonDivider />
                                        <LemonButton
                                            fullWidth
                                            status={broadcast.status === 'archived' ? 'default' : 'danger'}
                                            data-attr="broadcast-detail-archive"
                                            onClick={() =>
                                                broadcast.status === 'archived'
                                                    ? restoreBroadcast(broadcast)
                                                    : archiveBroadcast(broadcast)
                                            }
                                        >
                                            {broadcast.status === 'archived' ? 'Restore' : 'Archive'}
                                        </LemonButton>
                                        {broadcast.status === 'archived' && (
                                            <LemonButton
                                                fullWidth
                                                status="danger"
                                                data-attr="broadcast-detail-delete"
                                                onClick={() => deleteBroadcast(broadcast)}
                                            >
                                                Delete permanently
                                            </LemonButton>
                                        )}
                                    </>
                                }
                            />
                        </div>
                    )}
                </div>

                <div className="flex items-center gap-2">
                    <LemonTag type={broadcast?.status === 'active' ? 'success' : 'default'}>
                        {capitalizeFirstLetter(broadcast?.status ?? 'draft')}
                    </LemonTag>
                    <h1 className="m-0 text-2xl font-semibold">{name}</h1>
                </div>

                <BindLogic
                    logic={broadcastSentLogic}
                    props={{ id: broadcastId ?? 'new', parentRunId: latestBatchJobId ?? null }}
                >
                    <LemonTabs
                        activeKey={summaryTab}
                        onChange={(key) => setSummaryTab(key as BroadcastSummaryTab)}
                        data-attr="broadcast-summary-tabs"
                        tabs={[
                            {
                                key: 'overview' as const,
                                label: 'Overview',
                                content: <OverviewTab logicKey={logicKey} hasRun={!!latestBatchJobId} />,
                            },
                            {
                                key: 'content' as const,
                                label: 'Content',
                                content: <ContentTab workflowId={broadcastId ?? ''} />,
                            },
                            {
                                key: 'sent' as const,
                                label: 'Sent',
                                content: <SentTab workflowId={broadcastId ?? ''} />,
                            },
                            {
                                key: 'recipients' as const,
                                label: 'Recipients',
                                content: <RecipientsTab batchJobs={batchJobs} />,
                            },
                        ]}
                    />
                </BindLogic>

                <div className="flex flex-col gap-2">
                    <h2 className="m-0 text-lg font-semibold">Runs</h2>
                    <LemonTable
                        dataSource={batchJobs}
                        loading={batchJobsLoading}
                        rowKey="id"
                        columns={batchJobColumns}
                        nouns={['run', 'runs']}
                        emptyState="No runs yet. Scheduled broadcasts appear here after they send."
                    />
                </div>
            </div>
        </div>
    )
}
