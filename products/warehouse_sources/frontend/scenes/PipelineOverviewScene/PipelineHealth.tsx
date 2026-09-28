import { useValues } from 'kea'

import { LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import type { LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { DataHealthIssueApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

const STATUS_LABELS: Record<string, string> = {
    failed: 'Failed',
    billing_limit: 'Billing limit',
    degraded: 'Degraded',
    disabled: 'Disabled',
}

const STATUS_TAG_TYPES: Record<string, LemonTagType> = {
    failed: 'danger',
    billing_limit: 'warning',
    degraded: 'warning',
    disabled: 'muted',
}

const TYPE_LABELS: Record<string, string> = {
    external_data_sync: 'Sync',
    materialized_view: 'Materialized view',
    source: 'Source',
    destination: 'Destination',
    transformation: 'Transformation',
}

export function PipelineHealth(): JSX.Element {
    const { issuesBySeverity, healthIssues, healthIssuesLoading } = useValues(pipelineOverviewSceneLogic)

    if (healthIssuesLoading && healthIssues === null) {
        return <LemonSkeleton className="h-32 w-full" />
    }

    if (healthIssues !== null && issuesBySeverity.length === 0) {
        return (
            <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-muted">
                Every pipeline is healthy.
            </div>
        )
    }

    return (
        <LemonTable<DataHealthIssueApi>
            id="etl-health"
            dataSource={issuesBySeverity}
            rowKey="id"
            size="small"
            loading={healthIssuesLoading && healthIssues !== null}
            nouns={['issue', 'issues']}
            columns={[
                {
                    title: 'What',
                    key: 'name',
                    render: (_, issue) => (
                        <div className="flex min-w-0 flex-col">
                            {issue.url ? (
                                <Link to={issue.url} className="truncate font-medium">
                                    {issue.name}
                                </Link>
                            ) : (
                                <span className="truncate font-medium">{issue.name}</span>
                            )}
                            <span className="text-xs text-muted">
                                {TYPE_LABELS[issue.type] ?? issue.type}
                                {issue.source_type ? ` · ${issue.source_type}` : ''}
                            </span>
                        </div>
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    width: 140,
                    render: (_, issue) => (
                        <LemonTag type={STATUS_TAG_TYPES[issue.status] ?? 'default'}>
                            {STATUS_LABELS[issue.status] ?? issue.status}
                        </LemonTag>
                    ),
                },
                {
                    title: 'Error',
                    key: 'error',
                    render: (_, issue) =>
                        issue.error ? (
                            <span className="line-clamp-2 font-mono text-xs text-secondary">{issue.error}</span>
                        ) : (
                            <span className="text-muted">—</span>
                        ),
                },
                {
                    title: 'Since',
                    key: 'failed_at',
                    width: 140,
                    render: (_, issue) =>
                        issue.failed_at ? <TZLabel time={issue.failed_at} /> : <span className="text-muted">—</span>,
                },
            ]}
        />
    )
}
