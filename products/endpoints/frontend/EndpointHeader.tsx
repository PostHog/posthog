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
    const { endpoint, endpointLoading, localQuery, cacheAge, syncFrequency, isMaterialized } = useValues(
        endpointSceneLogic({ tabId })
    )
    const { endpointName, endpointDescription } = useValues(endpointLogic({ tabId }))
    const { setEndpointDescription, updateEndpoint } = useActions(endpointLogic({ tabId }))
    const { setLocalQuery, setCacheAge, setSyncFrequency, setIsMaterialized } = useActions(
        endpointSceneLogic({ tabId })
    )

    const hasNameChange = endpointName && endpointName !== endpoint?.name
    const hasDescriptionChange = endpointDescription !== null && endpointDescription !== endpoint?.description
    const hasQueryChange = localQuery !== null
    const hasCacheAgeChange = cacheAge !== (endpoint?.cache_age_seconds ?? null)
    const hasSyncFrequencyChange = syncFrequency !== (endpoint?.materialization?.sync_frequency ?? null)
    const hasIsMaterializedChange = isMaterialized !== null && isMaterialized !== endpoint?.is_materialized
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

        updateEndpoint(endpoint.name, updatePayload)
    }

    const handleDiscardChanges = (): void => {
        if (!endpoint) {
            return
        }
        setEndpointDescription(endpoint.description || '')
        setCacheAge(endpoint.cache_age_seconds ?? null)
        setSyncFrequency(endpoint.materialization?.sync_frequency ?? null)
        setIsMaterialized(null)
        setLocalQuery(null)
    }

    return (
        <>
            <SceneTitleSection
                name={endpointName || endpoint?.name}
                description={endpointDescription || endpoint?.description}
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
