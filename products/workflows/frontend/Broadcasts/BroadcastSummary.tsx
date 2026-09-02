import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft, IconCheck, IconExternal, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, LemonSelect, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { HogFlowBatchJobApi } from 'products/workflows/frontend/generated/api.schemas'

import { EmailMetricsSummary } from '../Workflows/EmailMetricsSummary'
import { BroadcastSendRow, BroadcastSendStatus, broadcastSentLogic } from './broadcastSentLogic'
import { broadcastsLogic } from './broadcastsLogic'
import { BroadcastSummaryTab, broadcastWizardLogic } from './broadcastWizardLogic'
import { renderEmailPreview } from './emailPreview'

const BATCH_JOB_STATUS_TAG: Record<string, LemonTagType> = {
    waiting: 'default',
    queued: 'warning',
    active: 'warning',
    completed: 'success',
    cancelled: 'muted',
    failed: 'danger',
}

const SEND_STATUS_TAG: Record<BroadcastSendStatus, { label: string; type: LemonTagType }> = {
    sent: { label: 'Sent', type: 'default' },
    delivered: { label: 'Delivered', type: 'success' },
    opened: { label: 'Opened', type: 'success' },
    clicked: { label: 'Clicked', type: 'success' },
    bounced: { label: 'Bounced', type: 'danger' },
    failed: { label: 'Failed', type: 'danger' },
    unsubscribed: { label: 'Unsubscribed', type: 'warning' },
    spam: { label: 'Marked as spam', type: 'danger' },
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

function ContentTab(): JSX.Element {
    const { email } = useValues(broadcastWizardLogic)

    return (
        <div className="flex flex-col gap-4">
            <Section title="Email">
                <div className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
                    <span className="text-muted">To</span>
                    <span className="font-mono text-xs">{email.to?.email || '-'}</span>
                    <span className="text-muted">Subject</span>
                    <span>{email.subject || 'No subject'}</span>
                    {email.preheader ? (
                        <>
                            <span className="text-muted">Preheader</span>
                            <span>{email.preheader}</span>
                        </>
                    ) : null}
                </div>
            </Section>
            <Section title="Preview">
                <p className="m-0 text-xs text-muted">
                    The email as stored on the broadcast, with its variables unrendered. The review step shows it
                    rendered against a real recipient.
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
            </Section>
        </div>
    )
}

function SentTab(): JSX.Element {
    const { filteredSends, sendsLoading, sendsFailed, statusFilter, selectedSend } = useValues(broadcastSentLogic)
    const { loadSends, setStatusFilter, selectRecipient } = useActions(broadcastSentLogic)
    const { email } = useValues(broadcastWizardLogic)

    useEffect(() => {
        loadSends()
    }, [loadSends])

    const columns: LemonTableColumns<BroadcastSendRow> = [
        {
            title: 'Last activity',
            key: 'lastEventAt',
            render: (_, row) => <TZLabel time={row.lastEventAt} />,
        },
        {
            title: 'Subject',
            key: 'subject',
            render: (_, row) => <span>{row.subject || '-'}</span>,
        },
        {
            title: 'Recipient',
            key: 'recipient',
            render: (_, row) => (
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={() => selectRecipient(row.recipient)}
                    data-attr="broadcast-view-recipient-email"
                >
                    <span className="font-mono text-xs">{row.recipient}</span>
                </LemonButton>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            width: 0,
            render: (_, row) => {
                const config = SEND_STATUS_TAG[row.status]
                return <LemonTag type={config.type}>{config.label}</LemonTag>
            },
        },
    ]

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <span className="text-sm text-muted">Filter by</span>
                <LemonSelect
                    size="small"
                    value={statusFilter}
                    onChange={(value) => setStatusFilter(value)}
                    options={[
                        { value: null, label: 'All statuses' },
                        ...(Object.keys(SEND_STATUS_TAG) as BroadcastSendStatus[]).map((status) => ({
                            value: status,
                            label: SEND_STATUS_TAG[status].label,
                        })),
                    ]}
                />
            </div>
            <LemonTable
                dataSource={filteredSends}
                loading={sendsLoading}
                rowKey="recipient"
                columns={columns}
                nouns={['recipient', 'recipients']}
                emptyState={
                    sendsFailed
                        ? "Couldn't load recipients. Refresh the page to try again."
                        : 'No sends recorded yet. Recipients appear here once the send produces engagement events.'
                }
            />
            <LemonModal
                isOpen={!!selectedSend}
                onClose={() => selectRecipient(null)}
                title={selectedSend ? `Email sent to ${selectedSend.recipient}` : ''}
                width={760}
            >
                {selectedSend ? (
                    <div className="flex flex-col gap-3">
                        <p className="m-0 text-xs text-muted">
                            The body is not stored per recipient, so this re-renders the broadcast's template against
                            this person's properties, the same way the worker did at send time.
                        </p>
                        <div className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
                            <span className="text-muted">Subject</span>
                            <span>{renderEmailPreview(email.subject, recipientPerson(selectedSend))}</span>
                        </div>
                        <iframe
                            srcDoc={renderEmailPreview(email.html, recipientPerson(selectedSend))}
                            sandbox=""
                            title="Email as sent to this recipient"
                            className="h-[26rem] w-full rounded border border-border bg-white"
                        />
                    </div>
                ) : null}
            </LemonModal>
        </div>
    )
}

// emailPreview renders against a person-shaped object; the Sent row already carries the properties.
function recipientPerson(send: BroadcastSendRow): { id: string; properties: Record<string, any> } {
    return { id: send.recipient, properties: send.personProperties }
}

function RecipientsTab({ batchJobs }: { batchJobs: HogFlowBatchJobApi[] }): JSX.Element {
    const { audienceProperties, scheduleSummary, conversion, goalEnabled, emailRateLimit } =
        useValues(broadcastWizardLogic)
    const firstRun = batchJobs[batchJobs.length - 1]

    return (
        <div className="flex flex-col gap-4">
            <Section title="Recipients">
                <p className="m-0 text-sm text-muted">This broadcast was sent to people matching:</p>
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
                            <LemonButton
                                type="tertiary"
                                size="small"
                                sideIcon={<IconExternal />}
                                to={urls.workflow(broadcastId, 'workflow')}
                                data-attr="broadcast-open-in-workflow-editor"
                            >
                                Open in workflow editor
                            </LemonButton>
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
                        { key: 'content' as const, label: 'Content', content: <ContentTab /> },
                        {
                            key: 'sent' as const,
                            label: 'Sent',
                            content: (
                                <BindLogic logic={broadcastSentLogic} props={{ id: broadcastId ?? 'new' }}>
                                    <SentTab />
                                </BindLogic>
                            ),
                        },
                        {
                            key: 'recipients' as const,
                            label: 'Recipients',
                            content: <RecipientsTab batchJobs={batchJobs} />,
                        },
                    ]}
                />

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
