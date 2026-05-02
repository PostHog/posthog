import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconClock, IconDatabase, IconInfo, IconList, IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { MaterializationStatusModal } from 'scenes/data-warehouse/saved_queries/MaterializationStatusModal'

import { endpointLogic } from '../endpointLogic'
import { endpointSceneLogic, MaterializationPreview } from '../endpointSceneLogic'

interface EndpointConfigurationProps {
    tabId: string
}

const DATA_FRESHNESS_OPTIONS: { value: number; label: string }[] = [
    { value: 900, label: '15 minutes' },
    { value: 1800, label: '30 minutes' },
    { value: 3600, label: '1 hour' },
    { value: 21600, label: '6 hours' },
    { value: 43200, label: '12 hours' },
    { value: 86400, label: '1 day (default)' },
    { value: 604800, label: '7 days' },
]

const BUCKET_OPTIONS: { value: string; label: string }[] = [
    { value: 'hour', label: 'Hour' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
]

const BUCKET_FN_TO_KEY: Record<string, string> = {
    toStartOfHour: 'hour',
    toStartOfDay: 'day',
    toStartOfWeek: 'week',
    toStartOfMonth: 'month',
}

function getStatusTagType(status: string | undefined): 'success' | 'danger' | 'warning' | 'default' {
    if (!status) {
        return 'warning'
    }
    switch (status.toLowerCase()) {
        case 'failed':
            return 'danger'
        case 'running':
            return 'warning'
        case 'completed':
            return 'success'
        default:
            return 'default'
    }
}

export function EndpointConfiguration({ tabId }: EndpointConfigurationProps): JSX.Element {
    const { endpoint } = useValues(endpointLogic({ tabId }))
    const { setDataFreshness } = useActions(endpointSceneLogic({ tabId }))
    const {
        dataFreshness,
        viewingVersion,
        materializationPreview,
        materializationPreviewLoading,
        isMaterialized: localIsMaterialized,
    } = useValues(endpointSceneLogic({ tabId }))
    const { loadMaterializationPreview } = useActions(endpointSceneLogic({ tabId }))
    const [leftActiveKeys, setLeftActiveKeys] = useState<string[]>(['materialization'])

    if (!endpoint) {
        return <></>
    }

    const effectiveDataFreshness =
        dataFreshness ?? viewingVersion?.data_freshness_seconds ?? endpoint.data_freshness_seconds ?? 86400
    const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint.is_materialized
    const isMaterialized = localIsMaterialized ?? baseIsMaterialized
    const materializationExpanded = leftActiveKeys.includes('materialization')

    return (
        <div className="flex gap-6">
            {/* Left column — settings (fixed width) */}
            <div className="w-120 shrink-0">
                <LemonCollapse
                    multiple
                    activeKeys={leftActiveKeys}
                    onChange={setLeftActiveKeys}
                    panels={[
                        {
                            key: 'materialization',
                            header: (
                                <div className="flex items-center gap-2">
                                    <IconDatabase className="text-lg" />
                                    <span>Materialization</span>
                                    <Tooltip title="We run your query on a schedule and store results in a table. When you execute this endpoint, we read from that stored table instead of running the full query again. You'll get results much faster, but data is only as fresh as the last time materialization ran.">
                                        <IconInfo className="text-lg text-secondary" />
                                    </Tooltip>
                                </div>
                            ),
                            content: <MaterializationContent tabId={tabId} />,
                        },
                        {
                            key: 'data-freshness',
                            header: (
                                <div className="flex items-center gap-2">
                                    <IconClock className="text-lg" />
                                    <span>Data freshness</span>
                                    <Tooltip title="Controls how long results are cached and how often materialized endpoints refresh.">
                                        <IconInfo className="text-lg text-secondary" />
                                    </Tooltip>
                                </div>
                            ),
                            content: (
                                <div className="flex flex-col gap-4 max-w-md p-1">
                                    <p className="text-sm text-secondary m-0">
                                        Choose how fresh the returned data should be. Shorter periods serve fresher
                                        data, but consume more compute.
                                    </p>
                                    <LemonSelect
                                        value={effectiveDataFreshness}
                                        onChange={setDataFreshness}
                                        options={DATA_FRESHNESS_OPTIONS}
                                    />
                                </div>
                            ),
                        },
                    ]}
                />
            </div>

            {/* Right column — query previews, visible when materialization is expanded and enabled */}
            {materializationExpanded && isMaterialized && (
                <div className="flex-1 min-w-0">
                    <LemonCollapse
                        multiple
                        defaultActiveKeys={['materialized-query']}
                        panels={[
                            {
                                key: 'materialized-query',
                                header: 'Query we materialize',
                                content: (
                                    <div className="p-1">
                                        <div className="flex items-center justify-between mb-4">
                                            <p className="text-sm text-secondary m-0">
                                                This is the query we run on a schedule and materialize results in S3.
                                                Variables are removed and their columns are added to the output columns.
                                            </p>
                                            <LemonButton
                                                size="xsmall"
                                                icon={<IconRefresh />}
                                                onClick={() => loadMaterializationPreview()}
                                                loading={materializationPreviewLoading}
                                                tooltip="Refresh preview"
                                            />
                                        </div>
                                        {materializationPreviewLoading && !materializationPreview && (
                                            <LemonSkeleton className="h-24 w-full" />
                                        )}
                                        {materializationPreview?.transformed_query && (
                                            <CodeSnippet language={Language.SQL} wrap>
                                                {materializationPreview.transformed_query}
                                            </CodeSnippet>
                                        )}
                                    </div>
                                ),
                            },
                            ...(materializationPreview?.execution_query
                                ? [
                                      {
                                          key: 'execution-query',
                                          header: 'Query we run',
                                          content: (
                                              <ExecutionQueryPanel materializationPreview={materializationPreview} />
                                          ),
                                      },
                                  ]
                                : []),
                        ]}
                    />
                </div>
            )}
        </div>
    )
}

function ExecutionQueryPanel({
    materializationPreview,
}: {
    materializationPreview: MaterializationPreview
}): JSX.Element {
    const displayQuery = materializationPreview.display_execution_query || materializationPreview.execution_query

    const reaggregates = materializationPreview.aggregates.filter((a) => a.reaggregate_fn)

    return (
        <div className="p-1">
            <p className="text-sm text-secondary mb-4">
                When you execute this endpoint, this is the query we run against the pre-computed table instead of
                scanning raw data. Variables from the request become filters in the WHERE clause.
            </p>
            <CodeSnippet language={Language.SQL} wrap>
                {displayQuery ?? ''}
            </CodeSnippet>
            {reaggregates.length > 0 && (
                <p className="text-xs text-secondary mt-3 m-0">
                    Aggregates like <code className="text-xs">count(*)</code> are re-aggregated as{' '}
                    <code className="text-xs">sum(count(*))</code> because results are pre-grouped into buckets.
                </p>
            )}
        </div>
    )
}

function MaterializationContent({ tabId }: { tabId: string }): JSX.Element {
    const { loadMaterializationStatus } = useActions(endpointLogic({ tabId }))
    const {
        endpoint,
        materializationStatus: loadedMaterializationStatus,
        materializationStatusLoading,
    } = useValues(endpointLogic({ tabId }))
    const { setIsMaterialized, setBucketOverride } = useActions(endpointSceneLogic({ tabId }))
    const {
        isMaterialized: localIsMaterialized,
        viewingVersion,
        materializationPreview,
        bucketOverrides,
    } = useValues(endpointSceneLogic({ tabId }))
    const [runsModalOpen, setRunsModalOpen] = useState(false)

    if (!endpoint) {
        return <></>
    }

    const savedQueryId =
        viewingVersion?.materialization?.saved_query_id ??
        loadedMaterializationStatus?.saved_query_id ??
        endpoint.materialization?.saved_query_id ??
        null

    const versionMaterialization = viewingVersion?.materialization ?? endpoint.materialization
    const freshMaterialization = loadedMaterializationStatus ?? versionMaterialization

    const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint.is_materialized
    const effectiveIsMaterialized = localIsMaterialized ?? baseIsMaterialized
    const effectiveMaterializationStatus = freshMaterialization?.status
    const effectiveLastMaterializedAt = freshMaterialization?.last_materialized_at
    const effectiveMaterializationError = freshMaterialization?.error

    const hasUnsavedMaterializationChange = localIsMaterialized !== null && localIsMaterialized !== baseIsMaterialized

    const canMaterialize =
        materializationPreview?.can_materialize ??
        freshMaterialization?.can_materialize ??
        endpoint.materialization?.can_materialize ??
        false
    const cannotMaterializeReason =
        materializationPreview?.reason ?? freshMaterialization?.reason ?? endpoint.materialization?.reason ?? null
    const isMaterialized = effectiveIsMaterialized || effectiveMaterializationStatus?.toLowerCase() === 'running'

    const handleToggleMaterialization = (): void => {
        setIsMaterialized(!isMaterialized)
    }

    const rangePairs = materializationPreview?.range_pairs ?? []

    return (
        <div className="p-1">
            <p className="text-sm text-secondary mb-6">
                Pre-compute query results on a schedule for faster response times.
            </p>

            {!canMaterialize && cannotMaterializeReason && (
                <LemonBanner type="info">{cannotMaterializeReason}</LemonBanner>
            )}

            {canMaterialize && (
                <div className="flex flex-col gap-4">
                    <LemonSwitch
                        label={isMaterialized ? 'Materialization enabled' : 'Enable materialization'}
                        checked={isMaterialized}
                        onChange={handleToggleMaterialization}
                        bordered
                    />

                    {hasUnsavedMaterializationChange && (
                        <LemonBanner type="info">
                            {isMaterialized
                                ? 'Save your changes to start materialization.'
                                : 'Save your changes to disable materialization.'}
                        </LemonBanner>
                    )}

                    {isMaterialized && !hasUnsavedMaterializationChange && (
                        <div className="space-y-3 p-4 bg-accent-3000 border border-border rounded">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <IconDatabase className="text-lg" />
                                    <span className="font-medium">Status</span>
                                </div>
                                <div className="flex items-center gap-2">
                                    <LemonTag type={getStatusTagType(effectiveMaterializationStatus)}>
                                        {effectiveMaterializationStatus || 'Pending'}
                                    </LemonTag>
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconRefresh />}
                                        onClick={() =>
                                            endpoint.name &&
                                            loadMaterializationStatus({
                                                name: endpoint.name,
                                                version:
                                                    viewingVersion?.version !== endpoint.current_version
                                                        ? viewingVersion?.version
                                                        : undefined,
                                            })
                                        }
                                        loading={materializationStatusLoading}
                                        tooltip="Refresh status"
                                    />
                                    {savedQueryId && (
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconList />}
                                            onClick={() => setRunsModalOpen(true)}
                                            tooltip="View materialization runs"
                                        />
                                    )}
                                </div>
                            </div>

                            {effectiveLastMaterializedAt && (
                                <div className="flex items-center gap-2 text-xs text-secondary">
                                    <IconRefresh className="text-base" />
                                    <span>
                                        Last materialized: {new Date(effectiveLastMaterializedAt).toLocaleString()}
                                    </span>
                                </div>
                            )}

                            {effectiveMaterializationError && (
                                <LemonBanner type="error" className="mt-2">
                                    {effectiveMaterializationError}
                                </LemonBanner>
                            )}
                        </div>
                    )}

                    {isMaterialized && rangePairs.length > 0 && (
                        <div className="space-y-3">
                            {rangePairs.map((pair) => (
                                <LemonField.Pure
                                    key={pair.column}
                                    label={
                                        <>
                                            <code>{pair.column}</code> bucket size
                                        </>
                                    }
                                    info="Your date range variables are bucketed into this interval in the stored materialized table. Smaller bucket - more precise results. Larger bucket - less granular results."
                                >
                                    <LemonSelect
                                        value={
                                            bucketOverrides[pair.column] || BUCKET_FN_TO_KEY[pair.bucket_fn] || 'day'
                                        }
                                        onChange={(value) => setBucketOverride(pair.column, value)}
                                        options={BUCKET_OPTIONS}
                                    />
                                </LemonField.Pure>
                            ))}
                        </div>
                    )}
                </div>
            )}
            <MaterializationStatusModal
                isOpen={runsModalOpen}
                onClose={() => setRunsModalOpen(false)}
                viewId={savedQueryId}
                viewName={endpoint.name}
                kind="endpoint"
            />
        </div>
    )
}
