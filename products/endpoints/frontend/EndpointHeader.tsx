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
    const { endpoint, endpointLoading, localQuery, dataFreshness, isMaterialized, viewingVersion } = useValues(
        endpointSceneLogic({ tabId })
    )
    const { endpointName, endpointDescription } = useValues(endpointLogic({ tabId }))
    const { setEndpointDescription, updateEndpoint } = useActions(endpointLogic({ tabId }))
    const { setLocalQuery, setDataFreshness, setIsMaterialized } = useActions(endpointSceneLogic({ tabId }))

    // When viewing a non-current version, target that version for updates
    const targetVersion =
        viewingVersion && viewingVersion.version !== endpoint?.current_version ? viewingVersion.version : undefined

    const hasNameChange = endpointName && endpointName !== endpoint?.name
    // When viewing a version, compare against that version's description
    const baseDescription = viewingVersion?.description ?? endpoint?.description
    const hasDescriptionChange = endpointDescription !== null && endpointDescription !== baseDescription
    const hasQueryChange = localQuery !== null
    // When viewing a version, compare against that version's values
    const baseDataFreshness = viewingVersion?.data_freshness_seconds ?? endpoint?.data_freshness_seconds ?? 86400
    const hasDataFreshnessChange = dataFreshness !== baseDataFreshness
    const baseIsMaterialized = viewingVersion?.is_materialized ?? endpoint?.is_materialized
    const hasIsMaterializedChange = isMaterialized !== null && isMaterialized !== baseIsMaterialized
    const hasChanges =
        hasNameChange || hasDescriptionChange || hasQueryChange || hasDataFreshnessChange || hasIsMaterializedChange

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
            data_freshness_seconds: hasDataFreshnessChange ? dataFreshness : undefined,
            query: hasQueryChange ? queryToSave : undefined,
            is_materialized: hasIsMaterializedChange ? isMaterialized : undefined,
        }

        updateEndpoint(endpoint.name, updatePayload, targetVersion ? { version: targetVersion } : undefined)
    }

    const handleDiscardChanges = (): void => {
        if (!endpoint) {
            return
        }
        // Reset to viewed version values if viewing a specific version
        const sourceDescription = viewingVersion?.description ?? endpoint.description
        const sourceDataFreshness = viewingVersion?.data_freshness_seconds ?? endpoint.data_freshness_seconds ?? 86400
        setEndpointDescription(sourceDescription || '')
        setDataFreshness(sourceDataFreshness)
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
                isLoading={endpointLoading && !endpoint}
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
