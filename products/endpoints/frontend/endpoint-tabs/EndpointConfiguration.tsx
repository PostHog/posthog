import { useActions, useValues } from 'kea'

import { IconDatabase, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSelect, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { endpointLogic } from '../endpointLogic'
import { endpointSceneLogic } from '../endpointSceneLogic'

interface EndpointConfigurationProps {
    tabId: string
}

const DATA_FRESHNESS_OPTIONS: { value: number; label: string }[] = [
    { value: 3600, label: '1 hour' },
    { value: 21600, label: '6 hours' },
    { value: 43200, label: '12 hours' },
    { value: 86400, label: '24 hours' },
    { value: 604800, label: '7 days' },
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
    const {
        endpoint,
        materializationStatus: loadedMaterializationStatus,
        materializationStatusLoading,
    } = useValues(endpointLogic({ tabId }))
    const { setDataFreshness, setIsMaterialized } = useActions(endpointSceneLogic({ tabId }))
    const {
        dataFreshness,
        isMaterialized: localIsMaterialized,
        viewingVersion,
    } = useValues(endpointSceneLogic({ tabId }))

    if (!endpoint) {
        return <></>
    }

    // When viewing a specific version, show that version's values
    // Local state overrides viewed version values (for pending changes)
    // materializationStatus (from refresh) takes priority over initial version data
    const versionMaterialization = viewingVersion?.materialization ?? endpoint.materialization
    const freshMaterialization = loadedMaterializationStatus ?? versionMaterialization

    const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint.is_materialized
    const effectiveDataFreshness =
        dataFreshness ?? viewingVersion?.data_freshness_seconds ?? endpoint.data_freshness_seconds ?? 86400
    const effectiveIsMaterialized = localIsMaterialized ?? baseIsMaterialized
    const effectiveMaterializationStatus = freshMaterialization?.status
    const effectiveLastMaterializedAt = freshMaterialization?.last_materialized_at
    const effectiveMaterializationError = freshMaterialization?.error

    const canMaterialize = freshMaterialization?.can_materialize ?? endpoint.materialization?.can_materialize ?? false
    const isMaterialized = effectiveIsMaterialized || effectiveMaterializationStatus?.toLowerCase() === 'running'
    const materializationStatus = effectiveMaterializationStatus
    const lastMaterializedAt = effectiveLastMaterializedAt

    const handleToggleMaterialization = (): void => {
        setIsMaterialized(!isMaterialized)
    }

    return (
        <SceneSection
            title="Configure this endpoint"
            description="If your use case does not require real-time data, consider materializing your endpoint resulting in faster response times, at the cost of slightly less fresh data."
        >
            <div className="flex flex-col gap-4 max-w-2xl">
                <LemonField.Pure
                    label="Data freshness"
                    info="How fresh the data should be. For materialized endpoints, this also controls how often data is refreshed."
                >
                    <LemonSelect
                        value={effectiveDataFreshness}
                        onChange={setDataFreshness}
                        options={DATA_FRESHNESS_OPTIONS}
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    label="Materialization"
                    info="Pre-compute and store query results in S3 for faster response times. Best for queries that don't need real-time data. Enabled by default for new endpoints."
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
                    {isMaterialized && (
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
                                </div>
                            </div>

                            {lastMaterializedAt && (
                                <div className="flex items-center gap-2 text-xs text-secondary">
                                    <IconRefresh className="text-base" />
                                    <span>Last materialized: {new Date(lastMaterializedAt).toLocaleString()}</span>
                                </div>
                            )}

                            {effectiveMaterializationError && (
                                <LemonBanner type="error" className="mt-2">
                                    {effectiveMaterializationError}
                                </LemonBanner>
                            )}
                        </div>
                    )}
                </div>
            </div>
            <LemonDivider />
        </SceneSection>
    )
}
