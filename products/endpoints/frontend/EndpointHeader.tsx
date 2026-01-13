import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { EndpointRequest } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'

import { endpointLogic } from './endpointLogic'
import { endpointSceneLogic } from './endpointSceneLogic'

export interface EndpointSceneHeaderProps {
    tabId: string
}

export const EndpointSceneHeader = ({ tabId }: EndpointSceneHeaderProps): JSX.Element => {
    const {
        endpoint,
        endpointLoading,
        localQuery,
        cacheAge,
        syncFrequency,
        isMaterialized,
        isViewingOldVersion,
        viewingVersion,
        selectedVersionData,
    } = useValues(endpointSceneLogic({ tabId }))
    const { endpointName, endpointDescription } = useValues(endpointLogic({ tabId }))
    const { setEndpointDescription, updateEndpoint } = useActions(endpointLogic({ tabId }))
    const {
        setLocalQuery,
        setCacheAge,
        setSyncFrequency,
        setIsMaterialized,
        returnToCurrentVersion,
        updateVersionMaterialization,
        loadSelectedVersion,
    } = useActions(endpointSceneLogic({ tabId }))

    // For old versions, compare against selectedVersionData; for current, compare against endpoint
    const baseData = isViewingOldVersion ? selectedVersionData : endpoint
    const hasNameChange = !isViewingOldVersion && endpointName && endpointName !== endpoint?.name
    const hasDescriptionChange =
        !isViewingOldVersion && endpointDescription !== null && endpointDescription !== endpoint?.description
    const hasQueryChange = !isViewingOldVersion && localQuery !== null
    const hasCacheAgeChange = cacheAge !== null && cacheAge !== (baseData?.cache_age_seconds ?? null)
    const hasSyncFrequencyChange =
        syncFrequency !== null &&
        syncFrequency !==
            (isViewingOldVersion
                ? (selectedVersionData?.sync_frequency ?? null)
                : (endpoint?.materialization?.sync_frequency ?? null))
    const hasIsMaterializedChange =
        isMaterialized !== null &&
        isMaterialized !== (isViewingOldVersion ? selectedVersionData?.is_materialized : endpoint?.is_materialized)
    const hasChanges =
        hasNameChange ||
        hasDescriptionChange ||
        hasQueryChange ||
        hasCacheAgeChange ||
        hasSyncFrequencyChange ||
        hasIsMaterializedChange

    const handleSave = (): void => {
        if (!endpoint) {
            return
        }

        // If viewing old version, only update version-specific fields
        if (isViewingOldVersion && viewingVersion !== null) {
            const updatePayload: Partial<Pick<EndpointVersionType, 'is_materialized' | 'sync_frequency'>> = {}
            if (hasIsMaterializedChange) {
                updatePayload.is_materialized = isMaterialized ?? false
            }
            if (hasSyncFrequencyChange) {
                updatePayload.sync_frequency = syncFrequency ?? undefined
            }
            updateVersionMaterialization(viewingVersion, updatePayload)
            // Reload the version data to see the changes
            loadSelectedVersion({ name: endpoint.name, version: viewingVersion })
            // Reset local state
            setIsMaterialized(null)
            setSyncFrequency(null)
            setCacheAge(null)
            return
        }

        // Current version update
        let queryToSave = (localQuery || endpoint?.query) as any

        if (queryToSave && isInsightVizNode(queryToSave)) {
            queryToSave = queryToSave.source
        }

        const updatePayload: Partial<EndpointRequest> = {
            description: hasDescriptionChange ? endpointDescription : undefined,
            cache_age_seconds: hasCacheAgeChange ? (cacheAge ?? undefined) : undefined,
            query: hasQueryChange ? queryToSave : undefined,
            is_materialized: hasIsMaterializedChange ? isMaterialized : undefined,
            sync_frequency: hasSyncFrequencyChange ? (syncFrequency ?? undefined) : undefined,
        }

        updateEndpoint(endpoint.name, updatePayload)
    }

    const handleDiscardChanges = (): void => {
        if (!endpoint) {
            return
        }
        // Reset to original values
        if (isViewingOldVersion && selectedVersionData) {
            // For old versions, reset to version data
            setCacheAge(null)
            setSyncFrequency(null)
            setIsMaterialized(null)
        } else {
            // For current version, reset to endpoint data
            setEndpointDescription(endpoint.description || '')
            setCacheAge(null)
            setSyncFrequency(null)
            setIsMaterialized(null)
            setLocalQuery(null)
        }
    }

    return (
        <>
            {isViewingOldVersion && (
                <div className="bg-warning-highlight border-warning border rounded p-3 mb-4 flex items-center justify-between">
                    <div>
                        <strong>Viewing historical version v{viewingVersion}</strong>
                        <br />
                        <span className="text-muted">
                            You can edit the configuration (materialization, sync frequency) for this version.
                        </span>
                    </div>
                    <LemonButton type="primary" onClick={returnToCurrentVersion}>
                        Return to current version (v{endpoint?.current_version})
                    </LemonButton>
                </div>
            )}
            <SceneTitleSection
                name={endpointName || endpoint?.name}
                description={endpointDescription || endpoint?.description}
                resourceType={{ type: 'endpoints' }}
                canEdit={true}
                // onNameChange={} - we explicitly disallow this
                onDescriptionChange={(description) => setEndpointDescription(description)}
                isLoading={endpointLoading}
                renameDebounceMs={200}
                actions={
                    <>
                        {endpoint && (
                            <LemonButton
                                type="secondary"
                                onClick={handleDiscardChanges}
                                disabledReason={!hasChanges && 'No changes to discard'}
                            >
                                Discard changes
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            onClick={handleSave}
                            disabledReason={
                                !endpoint ? 'Endpoint not loaded' : !hasChanges ? 'No changes to save' : undefined
                            }
                        >
                            Update
                        </LemonButton>
                    </>
                }
            />
        </>
    )
}
