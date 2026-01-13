import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconDatabase, IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonSelect,
    LemonSwitch,
    LemonTable,
    type LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import type { DataWarehouseSyncInterval, EndpointType, EndpointVersionType } from '~/types'

import { endpointLogic } from '../endpointLogic'
import { endpointSceneLogic } from '../endpointSceneLogic'

interface EndpointConfigurationProps {
    tabId: string
}

type CacheAgeOption = number | null
const CACHE_AGE_OPTIONS: { value: CacheAgeOption; label: string }[] = [
    { value: null, label: 'Default caching behavior' },
    { value: 300, label: '5 minutes' },
    { value: 900, label: '15 minutes' },
    { value: 1800, label: '30 minutes' },
    { value: 3600, label: '1 hour' },
    { value: 10800, label: '3 hours' },
    { value: 86400, label: '1 day' },
    { value: 259200, label: '3 days' },
]

const SYNC_FREQUENCY_OPTIONS: { value: DataWarehouseSyncInterval; label: string }[] = [
    { value: '1hour', label: 'Every hour' },
    { value: '6hour', label: 'Every 6 hours' },
    { value: '24hour', label: 'Once a day' },
    { value: '7day', label: 'Once a week' },
]

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
    const { loadMaterializationStatus } = useActions(endpointLogic({ tabId }))
    const { endpoint, materializationStatusLoading } = useValues(endpointLogic({ tabId }))
    const { setCacheAge, setSyncFrequency, setIsMaterialized, selectVersion, returnToCurrentVersion } = useActions(
        endpointSceneLogic({ tabId })
    )
    const {
        cacheAge,
        syncFrequency,
        isMaterialized: localIsMaterialized,
        isViewingOldVersion,
        selectedVersionData,
        versions,
        versionsLoading,
        viewingVersion,
    } = useValues(endpointSceneLogic({ tabId }))
    const sortedVersions = useMemo(() => [...versions].sort((a, b) => b.version - a.version), [versions])

    if (!endpoint) {
        return <></>
    }

    const activeVersionData: EndpointType | EndpointVersionType | null =
        isViewingOldVersion && selectedVersionData ? selectedVersionData : endpoint
    const baseCacheAge = activeVersionData?.cache_age_seconds ?? null
    const displayCacheAge = isViewingOldVersion ? baseCacheAge : (cacheAge ?? baseCacheAge)
    const displayIsMaterialized = isViewingOldVersion
        ? !!activeVersionData?.is_materialized
        : localIsMaterialized !== null
          ? localIsMaterialized
          : endpoint.is_materialized
    const displaySyncFrequency = isViewingOldVersion
        ? (activeVersionData?.sync_frequency ?? null)
        : (syncFrequency ?? endpoint.materialization?.sync_frequency ?? null)

    const activeMaterialization = activeVersionData?.materialization ?? endpoint.materialization
    const versionMaterializationError =
        activeVersionData && 'materialization_error' in activeVersionData
            ? activeVersionData.materialization_error
            : undefined
    const materializationStatus = activeMaterialization?.status
    const lastMaterializedAt =
        activeMaterialization?.last_materialized_at ||
        (activeVersionData && 'last_materialized_at' in activeVersionData
            ? activeVersionData.last_materialized_at
            : undefined)
    const materializationError = activeMaterialization?.error ?? versionMaterializationError
    const canMaterialize = activeMaterialization?.can_materialize ?? false

    const handleToggleMaterialization = (): void => {
        if (!canMaterialize && !isViewingOldVersion) {
            return
        }
        setIsMaterialized(!displayIsMaterialized)
    }

    const columns: LemonTableColumns<EndpointVersionType> = [
        {
            title: 'Version',
            dataIndex: 'version',
            render: function RenderVersion(_, item) {
                const isCurrent = item.version === endpoint.current_version
                const isViewing = viewingVersion === item.version
                const versionUrl = isCurrent
                    ? urls.endpoint(endpoint.name)
                    : `${urls.endpoint(endpoint.name)}?version=${item.version}`

                return (
                    <LemonTableLink
                        to={versionUrl}
                        title={
                            <div className="flex items-center gap-2">
                                <span>v{item.version}</span>
                                {isCurrent && <LemonTag size="small">Current</LemonTag>}
                                {isViewing && <LemonTag size="small">Viewing</LemonTag>}
                            </div>
                        }
                    />
                )
            },
        },
        createdAtColumn<EndpointVersionType>(),
        createdByColumn<EndpointVersionType>(),
        {
            title: 'Materialization',
            render: function RenderStatus(_, item) {
                const isCurrent = item.version === endpoint.current_version
                const materialized = isCurrent ? endpoint.is_materialized : item.is_materialized
                const sync = isCurrent ? endpoint.materialization?.sync_frequency : item.sync_frequency

                if (materialized && sync) {
                    return (
                        <span className="text-sm">
                            <LemonTag type="success" size="small">
                                {sync}
                            </LemonTag>
                        </span>
                    )
                }
                if (materialized) {
                    return (
                        <LemonTag type="success" size="small">
                            Enabled
                        </LemonTag>
                    )
                }
                return <span className="text-muted text-sm">—</span>
            },
        },
    ]

    return (
        <SceneSection
            title="Configure this endpoint"
            description="If your use case does not require real-time data, consider materializing your endpoint resulting in faster response times, at the cost of slightly less fresh data."
        >
            <div className="flex flex-col gap-4 max-w-2xl">
                <LemonField.Pure
                    label="Cache age"
                    info="How long cached results are served before re-running the query. Longer cache times improve performance but may return stale data."
                >
                    <LemonSelect
                        value={displayCacheAge}
                        onChange={setCacheAge}
                        options={CACHE_AGE_OPTIONS}
                        disabled={isViewingOldVersion}
                        disabledReason={
                            isViewingOldVersion
                                ? 'Cache age cannot be modified for historical versions. Only materialization and sync frequency can be changed.'
                                : undefined
                        }
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    label="Materialization"
                    info="Pre-compute and store query results in S3 for faster response times. Best for queries that don't need real-time data."
                >
                    <LemonSwitch
                        label="Enable materialization"
                        checked={displayIsMaterialized}
                        onChange={handleToggleMaterialization}
                        disabled={!canMaterialize}
                        disabledReason={!canMaterialize ? activeMaterialization?.reason : undefined}
                        bordered
                    />
                </LemonField.Pure>

                <div className="space-y-4">
                    {displayIsMaterialized && (
                        <div className="space-y-3 p-4 bg-accent-3000 border border-border rounded">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <IconDatabase className="text-lg" />
                                    <span className="font-medium">Materialization status</span>
                                </div>
                                <div className="flex items-center gap-2">
                                    <LemonTag type={getStatusTagType(materializationStatus)}>
                                        {materializationStatus || 'Pending'}
                                    </LemonTag>
                                    {!isViewingOldVersion && (
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconRefresh />}
                                            onClick={() => {
                                                if (endpoint.name) {
                                                    loadMaterializationStatus(endpoint.name)
                                                }
                                            }}
                                            loading={materializationStatusLoading}
                                            tooltip="Refresh status"
                                        />
                                    )}
                                </div>
                            </div>

                            {lastMaterializedAt && (
                                <div className="flex items-center gap-2 text-xs text-secondary">
                                    <IconRefresh className="text-base" />
                                    <span>Last materialized: {new Date(lastMaterializedAt).toLocaleString()}</span>
                                </div>
                            )}

                            {materializationError && (
                                <LemonBanner type="error" className="mt-2">
                                    {materializationError}
                                </LemonBanner>
                            )}
                        </div>
                    )}

                    {displayIsMaterialized && (
                        <LemonField.Pure
                            label="Sync frequency"
                            info="How often the materialized data is refreshed with new query results. More frequent syncs = fresher data but higher costs."
                        >
                            <LemonSelect
                                value={displaySyncFrequency || '24hour'}
                                onChange={setSyncFrequency}
                                options={SYNC_FREQUENCY_OPTIONS}
                            />
                        </LemonField.Pure>
                    )}
                </div>
            </div>
            <LemonDivider />
            <div className="mt-4 max-w-4xl">
                <h3 className="text-lg font-semibold mb-1">Version history</h3>
                <p className="text-muted mb-3">View previous versions and switch between snapshots.</p>
                <LemonTable
                    dataSource={sortedVersions}
                    columns={columns}
                    loading={versionsLoading}
                    rowKey="version"
                    pagination={{ pageSize: 10, hideOnSinglePage: true }}
                    emptyState="No versions yet"
                />
            </div>
        </SceneSection>
    )
}
