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
    const { endpointName, endpointDescription } = useValues(endpointLogic({ tabId }))
    const { setEndpointDescription, updateEndpoint, createEndpoint } = useActions(endpointLogic({ tabId }))
    const { setLocalQuery } = useActions(endpointSceneLogic({ tabId }))

    const isNewEndpoint = !endpoint?.name || endpoint.name === 'new-endpoint'

    const hasNameChange = endpointName && endpointName !== endpoint?.name
    const hasDescriptionChange = endpointDescription !== null && endpointDescription !== endpoint?.description
    const hasQueryChange = localQuery !== null
    const hasChanges = hasNameChange || hasDescriptionChange || hasQueryChange

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
                query: queryToSave,
            })
        }
    }

    const handleDiscardChanges = (): void => {
        if (endpoint) {
            setEndpointDescription(endpoint.description || '')
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
                // onNameChange={(name) => setEndpointName(name)}
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
