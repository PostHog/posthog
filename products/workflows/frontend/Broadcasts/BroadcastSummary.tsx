import { useValues } from 'kea'

import { IconArrowLeft, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { HogFlowBatchJobApi } from 'products/workflows/frontend/generated/api.schemas'

import { EmailMetricsSummary } from '../Workflows/EmailMetricsSummary'
import { broadcastWizardLogic } from './broadcastWizardLogic'

const BATCH_JOB_STATUS_TAG: Record<string, 'success' | 'default' | 'warning' | 'danger' | 'muted'> = {
    waiting: 'default',
    queued: 'warning',
    active: 'warning',
    completed: 'success',
    cancelled: 'muted',
    failed: 'danger',
}

export function BroadcastSummary(): JSX.Element {
    const { broadcast, broadcastId, name, audienceProperties, email, scheduleSummary, batchJobs, batchJobsLoading } =
        useValues(broadcastWizardLogic)

    const logicKey = `broadcast-${broadcastId}`
    // Mounting with force params here pins the metrics query to this broadcast; EmailMetricsSummary
    // reads the same keyed logic below.
    useValues(
        appMetricsLogic({
            logicKey,
            loadOnMount: true,
            loadOnChanges: true,
            forceParams: {
                appSource: 'hog_flow',
                appSourceId: broadcastId ?? undefined,
                breakdownBy: 'metric_name',
                dateFrom: '-30d',
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
                <div className="flex items-center justify-between">
                    <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.broadcasts()}>
                        Broadcasts
                    </LemonButton>
                    {broadcastId && (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            sideIcon={<IconExternal />}
                            to={urls.workflow(broadcastId, 'workflow')}
                            data-attr="broadcast-open-in-workflow-editor"
                        >
                            Open in workflow editor
                        </LemonButton>
                    )}
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
                    <h2 className="m-0 text-lg font-semibold">Performance (last 30 days)</h2>
                    <EmailMetricsSummary logicKey={logicKey} />
                </div>

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
