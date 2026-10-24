import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { NodeDetailLineage } from 'products/data_modeling/frontend/nodeDetail/NodeDetailLineage'
import { nodeDetailSceneLogic } from 'products/data_modeling/frontend/nodeDetail/nodeDetailSceneLogic'
import { NodeDetailTests } from 'products/data_modeling/frontend/nodeDetail/NodeDetailTests'

export function EndpointModelPanel({ id, tab }: { id: string; tab: 'lineage' | 'data-quality' }): JSX.Element {
    const logic = nodeDetailSceneLogic({ id })
    const { node, nodeLoading, savedQuery, savedQueryLoading, savedQueryError } = useValues(logic)
    const { loadNode, loadSavedQuery } = useActions(logic)

    if (nodeLoading || (tab === 'data-quality' && savedQueryLoading)) {
        return <Spinner />
    }

    if (!node || (tab === 'data-quality' && (savedQueryError || !savedQuery))) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Retry', onClick: () => (node ? loadSavedQuery() : loadNode()) }}
            >
                Couldn't load this version's model. Try again.
            </LemonBanner>
        )
    }

    return tab === 'lineage' ? <NodeDetailLineage id={id} /> : <NodeDetailTests id={id} />
}
