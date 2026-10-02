import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'
import { lineageNodeUrl } from 'products/data_modeling/frontend/lineage/lineageNodeUrl'

import { EndpointTab, endpointSceneLogic } from '../endpointSceneLogic'
import { endpointLineageLogic } from './endpointLineageLogic'

function LineageEmptyState({ body, endpointName }: { body: string; endpointName?: string }): JSX.Element {
    return (
        <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded border bg-bg-light p-6 text-center">
            <div className="max-w-120">
                <h3 className="mb-2">No lineage yet</h3>
                <p className="mb-0 text-secondary">{body}</p>
            </div>
            {endpointName && (
                <LemonButton
                    type="secondary"
                    size="small"
                    to={combineUrl(urls.endpoint(endpointName), { tab: EndpointTab.CONFIGURATION }).url}
                >
                    Open configuration
                </LemonButton>
            )}
        </div>
    )
}

function EndpointLineageGraph({ savedQueryId }: { savedQueryId: string }): JSX.Element {
    const logic = endpointLineageLogic({ savedQueryId })
    const { lineage, lineageLoading, lineageMissing, lineageFailed, currentNodeId } = useValues(logic)
    const { loadLineage } = useActions(logic)

    if (lineageFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadLineage }}>
                Couldn't load lineage.
            </LemonBanner>
        )
    }

    if (lineageMissing) {
        return (
            <LineageEmptyState body="This endpoint's model isn't in the lineage graph yet. Check back after its next run." />
        )
    }

    return (
        <div className="h-[70vh] min-h-[400px] w-full border rounded bg-bg-light overflow-hidden">
            <LineageGraph
                nodes={lineage?.nodes ?? []}
                edges={lineage?.edges ?? []}
                currentNodeId={currentNodeId}
                loading={lineageLoading}
                variant="full"
                interactive
                showControls
                showMinimap
                onNodeClick={(node) => router.actions.push(lineageNodeUrl(node, 'lineage'))}
                panels={
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.models('lineage')}
                        tooltip="Open the full graph"
                        icon={<IconExternal />}
                    />
                }
            />
        </div>
    )
}

export function EndpointLineage(): JSX.Element {
    const { endpoint, viewingVersion } = useValues(endpointSceneLogic)

    if (!endpoint) {
        return <></>
    }

    const savedQueryId = (viewingVersion ?? endpoint).materialization?.saved_query_id ?? null

    if (!savedQueryId) {
        return (
            <LineageEmptyState
                body="Lineage shows the tables and models this endpoint reads from. It's available once this version is materialized."
                endpointName={endpoint.name}
            />
        )
    }

    return <EndpointLineageGraph savedQueryId={savedQueryId} />
}
