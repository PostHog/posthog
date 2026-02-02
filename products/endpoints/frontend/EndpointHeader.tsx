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
    const { endpoint, endpointLoading, localQuery, cacheAge, syncFrequency, isMaterialized, viewingVersion } =
        useValues(endpointSceneLogic({ tabId }))
    const { endpointName, endpointDescription } = useValues(endpointLogic({ tabId }))
    const { setEndpointDescription, updateEndpoint } = useActions(endpointLogic({ tabId }))
    const { setLocalQuery, setCacheAge, setSyncFrequency, setIsMaterialized } = useActions(
        endpointSceneLogic({ tabId })
    )

    // When viewing a non-current version, target that version for updates
    const targetVersion =
        viewingVersion && viewingVersion.version !== endpoint?.current_version ? viewingVersion.version : undefined

    const hasNameChange = endpointName && endpointName !== endpoint?.name
    // When viewing a version, compare against that version's description
    const baseDescription = viewingVersion?.description ?? endpoint?.description
    const hasDescriptionChange = endpointDescription !== null && endpointDescription !== baseDescription
    const hasQueryChange = localQuery !== null
    // When viewing a version, compare against that version's values
    const baseCacheAge = viewingVersion?.cache_age_seconds ?? endpoint?.cache_age_seconds ?? null
    const hasCacheAgeChange = cacheAge !== null && cacheAge !== baseCacheAge
    const baseSyncFrequency =
        viewingVersion?.materialization?.sync_frequency ?? endpoint?.materialization?.sync_frequency ?? null
    const hasSyncFrequencyChange = syncFrequency !== null && syncFrequency !== baseSyncFrequency
    const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint?.is_materialized
    const hasIsMaterializedChange = isMaterialized !== null && isMaterialized !== baseIsMaterialized
    const hasChanges =
        hasNameChange ||
        hasDescriptionChange ||
        hasQueryChange ||
        hasCacheAgeChange ||
        hasSyncFrequencyChange ||
        hasIsMaterializedChange

    const handleSave = (): void => {
        let queryToSave = (localQuery || endpoint?.query) as any

        if (queryToSave && isInsightVizNode(queryToSave)) {
            queryToSave = queryToSave.source
        }

        if (!endpoint) {
            return
        }

        const updatePayload: Partial<EndpointRequest> = {
            description: hasDescriptionChange ? endpointDescription : undefined,
            cache_age_seconds: hasCacheAgeChange ? (cacheAge ?? undefined) : undefined,
            query: hasQueryChange ? queryToSave : undefined,
            is_materialized: hasIsMaterializedChange ? isMaterialized : undefined,
            sync_frequency: hasSyncFrequencyChange ? (syncFrequency ?? undefined) : undefined,
        }

        updateEndpoint(endpoint.name, updatePayload, targetVersion ? { version: targetVersion } : undefined)
    }

    const handleDiscardChanges = (): void => {
        if (!endpoint) {
            return
        }
        // Reset to viewed version values if viewing a specific version
        const sourceDescription = viewingVersion?.description ?? endpoint.description
        const sourceCacheAge = viewingVersion?.cache_age_seconds ?? endpoint.cache_age_seconds
        const sourceSyncFrequency =
            viewingVersion?.materialization?.sync_frequency ?? endpoint.materialization?.sync_frequency
        setEndpointDescription(sourceDescription || '')
        setCacheAge(sourceCacheAge ?? null)
        setSyncFrequency(sourceSyncFrequency ?? null)
        setIsMaterialized(null)
        setLocalQuery(null)
    }

    return (
        <>
            <SceneTitleSection
                name={endpointName || endpoint?.name}
                description={endpointDescription ?? viewingVersion?.description ?? endpoint?.description}
                resourceType={{ type: 'endpoints' }}
                canEdit
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
                                !endpoint
                                    ? 'Endpoint not loaded'
                                    : !hasChanges
                                      ? 'No changes to save'
                                      : hasQueryChange && targetVersion
                                        ? 'Query can only be changed when on the latest version'
                                        : undefined
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
