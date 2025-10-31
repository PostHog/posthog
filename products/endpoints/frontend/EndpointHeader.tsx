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
    const { endpoint, endpointLoading, localQuery } = useValues(endpointSceneLogic({ tabId }))
    const { endpointName, endpointDescription, cacheAge, syncFrequency, isMaterialized } = useValues(
        endpointLogic({ tabId })
    )
    const {
        setEndpointDescription,
        updateEndpoint,
        createEndpoint,
        setCacheAge,
        setSyncFrequency,
        setIsMaterialized,
        unmaterializeEndpoint,
    } = useActions(endpointLogic({ tabId }))
    const { setLocalQuery } = useActions(endpointSceneLogic({ tabId }))

    const isNewEndpoint = !endpoint?.name || endpoint.name === 'new-endpoint'

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

        if (isNewEndpoint) {
            createEndpoint({
                name: endpointName || endpoint?.name || '',
                description: endpointDescription || endpoint?.description,
                query: queryToSave,
            })
        } else {
            if (!isMaterialized) {
                unmaterializeEndpoint(endpoint?.name)
                return
            }
            const updatePayload: Partial<EndpointRequest> = {
                name: endpointName || endpoint?.name,
                description: endpointDescription || endpoint?.description,
                cache_age_seconds: cacheAge ?? undefined,
                is_materialized: isMaterialized ?? undefined,
                query: queryToSave,
            }

            // Only include sync_frequency if it's not null
            if (syncFrequency) {
                updatePayload.sync_frequency = syncFrequency
            }

            updateEndpoint(endpoint.name, updatePayload)
        }
    }

    const handleDiscardChanges = (): void => {
        if (endpoint) {
            setEndpointDescription(endpoint.description || '')
            setCacheAge(endpoint.cache_age_seconds ?? null)
            setSyncFrequency(endpoint.materialization?.sync_frequency ?? null)
            setIsMaterialized(null)
        }
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
                        {!isNewEndpoint && (
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
                            disabledReason={!hasChanges && !isNewEndpoint && 'No changes to save'}
                        >
                            {isNewEndpoint ? 'Create' : 'Update'}
                        </LemonButton>
                    </>
                }
            />
        </>
    )
}
