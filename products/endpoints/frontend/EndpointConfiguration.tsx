import { useActions, useValues } from 'kea'

import { IconDatabase, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonDivider, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { DataWarehouseSyncInterval } from '~/types'

import { endpointLogic } from './endpointLogic'

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

export function EndpointConfiguration({ tabId }: EndpointConfigurationProps): JSX.Element {
    const { setCacheAge, setSyncFrequency, setIsMaterialized } = useActions(endpointLogic({ tabId }))
    const {
        endpoint,
        cacheAge,
        syncFrequency,
        isMaterialized: localIsMaterialized,
    } = useValues(endpointLogic({ tabId }))

    if (!endpoint) {
        return <></>
    }

    const canMaterialize = endpoint.materialization?.can_materialize ?? false
    const isMaterialized = localIsMaterialized !== null ? localIsMaterialized : endpoint.is_materialized
    const materializationStatus = endpoint.materialization?.status
    const lastMaterializedAt = endpoint.materialization?.last_materialized_at

    const handleToggleMaterialization = (): void => {
        setIsMaterialized(!isMaterialized)
    }

    return (
        <SceneSection title="Configure this endpoint">
            <div className="flex flex-col gap-4 max-w-2xl">
                <LemonField.Pure
                    label="Cache age"
                    info="Cache age defines how long your endpoint will return cached results before running the query again
                    and refreshing the results."
                >
                    <LemonSelect value={cacheAge} onChange={setCacheAge} options={CACHE_AGE_OPTIONS} />
                </LemonField.Pure>
                <LemonField.Pure
                    label="Materialization"
                    info="Pre-compute and store query results in S3 for better query performance."
                >
                    <LemonSwitch
                        label="Enable materialization"
                        checked={isMaterialized}
                        onChange={handleToggleMaterialization}
                        disabled={!canMaterialize}
                        disabledReason={!canMaterialize ? endpoint.materialization?.reason : undefined}
                        bordered
                    />
                </LemonField.Pure>

                <div className="space-y-4">
                    {endpoint.is_materialized && (
                        <div className="space-y-3 p-4 bg-accent-3000 border border-border rounded">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <IconDatabase className="text-lg" />
                                    <span className="font-medium">Materialization status</span>
                                </div>
                                <span className="text-xs px-2 py-1 bg-success-highlight text-success rounded">
                                    {materializationStatus || 'Active'}
                                </span>
                            </div>

                            {lastMaterializedAt && (
                                <div className="flex items-center gap-2 text-xs text-secondary">
                                    <IconRefresh className="text-base" />
                                    <span>Last materialized: {new Date(lastMaterializedAt).toLocaleString()}</span>
                                </div>
                            )}

                            {endpoint.materialization?.error && (
                                <LemonBanner type="error" className="mt-2">
                                    {endpoint.materialization.error}
                                </LemonBanner>
                            )}
                        </div>
                    )}

                    {isMaterialized && (
                        <LemonField.Pure label="Sync frequency" info="How often the materialization is refreshed">
                            <LemonSelect
                                value={syncFrequency || '24hour'}
                                onChange={setSyncFrequency}
                                options={SYNC_FREQUENCY_OPTIONS}
                                disabledReason={!isMaterialized ? 'Requires materializing the endpoint.' : undefined}
                            />
                        </LemonField.Pure>
                    )}
                </div>
            </div>
            <LemonDivider />
        </SceneSection>
    )
}
