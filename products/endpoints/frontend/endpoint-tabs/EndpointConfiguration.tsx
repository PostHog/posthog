import { useActions, useValues } from 'kea'

import { IconDatabase, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import type { DataWarehouseSyncInterval } from '~/types'

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
    const { setCacheAge, setSyncFrequency, setIsMaterialized } = useActions(endpointSceneLogic({ tabId }))
    const {
        cacheAge,
        syncFrequency,
        isMaterialized: localIsMaterialized,
        isViewingOldVersion,
        selectedVersionData,
    } = useValues(endpointSceneLogic({ tabId }))

    if (!endpoint) {
        return <></>
    }

    // Determine the base data source: selectedVersionData for old versions, endpoint for current
    const baseData = isViewingOldVersion && selectedVersionData ? selectedVersionData : endpoint
    const baseMaterialization = baseData?.materialization

    // Display values: local state overrides base data when user has made changes
    const displayCacheAge = cacheAge ?? baseData?.cache_age_seconds ?? null
    const displayIsMaterialized = localIsMaterialized ?? baseData?.is_materialized ?? false
    const displaySyncFrequency =
        syncFrequency ??
        (isViewingOldVersion
            ? (selectedVersionData?.sync_frequency ?? null)
            : (endpoint.materialization?.sync_frequency ?? null))

    // Materialization status comes directly from the base data's materialization object
    const materializationStatus = baseMaterialization?.status
    const lastMaterializedAt = baseMaterialization?.last_materialized_at
    const materializationError = baseMaterialization?.error
    const canMaterialize = baseMaterialization?.can_materialize ?? false

    const handleToggleMaterialization = (): void => {
        if (!canMaterialize) {
            return
        }
        setIsMaterialized(!displayIsMaterialized)
    }

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
                    <LemonSelect value={displayCacheAge} onChange={setCacheAge} options={CACHE_AGE_OPTIONS} />
                </LemonField.Pure>
                <LemonField.Pure
                    label="Materialization"
                    info="Pre-compute and store query results in S3 for faster response times. Best for queries that don't need real-time data. Enabled by default for new endpoints."
                >
                    <LemonSwitch
                        label="Enable materialization"
                        checked={displayIsMaterialized}
                        onChange={handleToggleMaterialization}
                        disabled={!canMaterialize}
                        disabledReason={!canMaterialize ? baseMaterialization?.reason : undefined}
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
        </SceneSection>
    )
}
