import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { isInsightVizNode } from '~/queries/utils'

import { endpointLogic } from './endpointLogic'
import { endpointSceneLogic } from './endpointSceneLogic'

export interface EndpointSceneHeaderProps {
    tabId: string
}

export const EndpointSceneHeader = ({ tabId }: EndpointSceneHeaderProps): JSX.Element => {
    const { endpoint, endpointLoading, localQuery } = useValues(endpointSceneLogic({ tabId }))
    const { endpointName, endpointDescription, cacheAge } = useValues(endpointLogic({ tabId }))
    const { setEndpointDescription, updateEndpoint, createEndpoint, setCacheAge } = useActions(endpointLogic({ tabId }))
    const { setLocalQuery } = useActions(endpointSceneLogic({ tabId }))

    const isNewEndpoint = !endpoint?.name || endpoint.name === 'new-endpoint'

    const hasNameChange = endpointName && endpointName !== endpoint?.name
    const hasDescriptionChange = endpointDescription !== null && endpointDescription !== endpoint?.description
    const hasQueryChange = localQuery !== null
    const hasCacheAgeChange = cacheAge !== (endpoint?.cache_age_seconds ?? null)
    const hasChanges = hasNameChange || hasDescriptionChange || hasQueryChange || hasCacheAgeChange

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
            updateEndpoint(endpoint.name, {
                name: endpointName || endpoint?.name,
                description: endpointDescription || endpoint?.description,
                cache_age_seconds: cacheAge ?? undefined,
                query: queryToSave,
            })
        }
    }

    const handleDiscardChanges = (): void => {
        if (endpoint) {
            setEndpointDescription(endpoint.description || '')
            setCacheAge(endpoint.cache_age_seconds ?? null)
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
