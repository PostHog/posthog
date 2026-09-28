import { useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import type { LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { ExternalDataSourceSerializersApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

const STATUS_TAG_TYPES: Record<string, LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Error: 'danger',
    Paused: 'warning',
    Cancelled: 'warning',
}

export function ConnectedSources(): JSX.Element {
    const { managedSources, sourcesLoading, otherSourceCount } = useValues(pipelineOverviewSceneLogic)

    if (sourcesLoading && managedSources === null) {
        return <LemonSkeleton className="h-32 w-full" />
    }

    if (managedSources !== null && managedSources.length === 0) {
        return (
            <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-muted">
                No sources are imported on a schedule yet.
            </div>
        )
    }

    return (
        <LemonTable<ExternalDataSourceSerializersApi>
            id="etl-sources"
            dataSource={managedSources ?? []}
            rowKey="id"
            size="small"
            loading={sourcesLoading && managedSources !== null}
            nouns={['source', 'sources']}
            columns={[
                {
                    title: 'Source',
                    key: 'source_type',
                    render: (_, source) => (
                        <div className="flex min-w-0 flex-col">
                            <Link to={urls.dataWarehouseSource(source.id, 'schemas')} className="truncate font-medium">
                                {source.source_type}
                            </Link>
                            {source.prefix ? <span className="text-xs text-muted">{source.prefix}</span> : null}
                        </div>
                    ),
                },
                {
                    title: 'Tables',
                    key: 'schemas',
                    align: 'right',
                    width: 90,
                    // Only the tables actually syncing, so this matches what the pipeline does
                    // rather than everything the source could offer.
                    render: (_, source) => (source.schemas ?? []).filter((schema: any) => schema.should_sync).length,
                },
                {
                    title: 'Status',
                    key: 'status',
                    width: 130,
                    render: (_, source) =>
                        source.status ? (
                            <LemonTag type={STATUS_TAG_TYPES[source.status] ?? 'default'}>{source.status}</LemonTag>
                        ) : (
                            <span className="text-muted">—</span>
                        ),
                },
                {
                    title: 'Last run',
                    key: 'last_run_at',
                    width: 140,
                    render: (_, source) =>
                        source.last_run_at ? (
                            <TZLabel time={source.last_run_at} />
                        ) : (
                            <span className="text-muted">Never</span>
                        ),
                },
            ]}
            footer={
                <LemonButton to={urls.sources()} type="tertiary" fullWidth center data-attr="etl-all-sources">
                    {otherSourceCount > 0
                        ? `Show all sources, including ${otherSourceCount} queried in place`
                        : 'Show all sources'}
                </LemonButton>
            }
        />
    )
}
