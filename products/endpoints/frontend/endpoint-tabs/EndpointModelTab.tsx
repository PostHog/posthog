import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { nodeDetailSceneLogic } from 'scenes/models/nodeDetailSceneLogic'
import { NodeDetailLineage } from 'scenes/models/tabs/NodeDetailLineage'
import { NodeDetailTests } from 'scenes/models/tabs/NodeDetailTests'

import { endpointSceneLogic } from '../endpointSceneLogic'

export function EndpointModelTab({ tab }: { tab: 'lineage' | 'tests' }): JSX.Element {
    const { endpoint, endpointLoading, viewingVersion } = useValues(endpointSceneLogic)
    const { searchParams } = useValues(router)
    const version = viewingVersion ?? endpoint
    const requestedVersion = searchParams.version ? Number(searchParams.version) : endpoint?.current_version
    const displayedVersion = viewingVersion?.version ?? endpoint?.current_version

    if (endpointLoading || !version || (requestedVersion && requestedVersion !== displayedVersion)) {
        return <Spinner />
    }

    if (!version.node_id) {
        return (
            <LemonBanner type="info">
                {version.model_unavailable_reason ||
                    'This version does not have a model yet. Save a new version to create its model.'}
            </LemonBanner>
        )
    }

    return <EndpointModelPanel key={version.node_id} id={version.node_id} tab={tab} />
}

function EndpointModelPanel({ id, tab }: { id: string; tab: 'lineage' | 'tests' }): JSX.Element {
    const { node, nodeLoading, savedQuery, savedQueryLoading, savedQueryError } = useValues(
        nodeDetailSceneLogic({ id })
    )
    const { loadNode, loadSavedQuery } = useActions(nodeDetailSceneLogic({ id }))

    if (nodeLoading || (tab === 'tests' && savedQueryLoading)) {
        return <Spinner />
    }

    if (!node || (tab === 'tests' && (savedQueryError || !savedQuery))) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Retry', onClick: () => (node ? loadSavedQuery() : loadNode()) }}
            >
                Couldn't load this version's model. Try again.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            {tab === 'lineage' ? (
                <NodeDetailLineage id={id} />
            ) : (
                <NodeDetailTests id={id} subjectId={node.saved_query_id ?? ''} />
            )}
        </div>
    )
}
