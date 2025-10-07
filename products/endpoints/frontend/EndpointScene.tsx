import { BindLogic, useActions, useValues } from 'kea'

import 'lib/lemon-ui/LemonModal/LemonModal'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, Node } from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode, isInsightVizNode } from '~/queries/utils'

import { EndpointSceneHeader } from './EndpointHeader'
import { endpointSceneLogic } from './endpointSceneLogic'

interface EndpointProps {
    tabId?: string
}

export const scene: SceneExport = {
    component: EndpointScene,
    logic: endpointSceneLogic,
}

export function EndpointScene({ tabId }: EndpointProps = {}): JSX.Element {
    if (!tabId) {
        throw new Error('<EndpointScene /> must receive a tabId prop')
    }
    const { endpoint, endpointLoading, showQueryEditor, queryToRender } = useValues(endpointSceneLogic({ tabId }))
    const { setLocalQuery } = useActions(endpointSceneLogic({ tabId }))

    const setQuery = (query: Node): void => {
        let actualQuery: Node
        if (isInsightVizNode(query)) {
            actualQuery = query.source
        } else if (isHogQLQuery(query) || isInsightQueryNode(query)) {
            actualQuery = query
        } else {
            actualQuery = (query as DataTableNode).source
        }
        setLocalQuery(actualQuery)
    }

    return (
        <BindLogic logic={endpointSceneLogic} props={{ tabId }}>
            <SceneContent className="Endpoint">
                <EndpointSceneHeader tabId={tabId} />
                <div className="flex gap-4">
                    {/* Left side: Query editor */}
                    <div className="flex-1">
                        {queryToRender && !endpointLoading ? (
                            <Query
                                key={`${endpoint?.name}-${showQueryEditor}`}
                                query={queryToRender}
                                setQuery={setQuery}
                                readOnly={false}
                                editMode={true}
                                context={{
                                    showQueryEditor,
                                    showOpenEditorButton: false,
                                }}
                            />
                        ) : null}
                    </div>

                    {/* Right side: Variables & Configuration */}
                    <div className="w-80 flex flex-col gap-4">
                        {/* Variables */}
                        <div className="border rounded p-4">
                            <h3 className="text-sm font-semibold mb-2">Variables</h3>
                            <p className="text-muted text-xs">Variables panel placeholder</p>
                        </div>

                        {/* Configuration */}
                        <div className="border rounded p-4">
                            <h3 className="text-sm font-semibold mb-2">Configuration</h3>
                            <p className="text-muted text-xs">Materialization options placeholder</p>
                        </div>

                        {/* Versions */}
                        <div className="border rounded p-4">
                            <h3 className="text-sm font-semibold mb-2">Versions</h3>
                            <p className="text-muted text-xs">Version history placeholder</p>
                        </div>
                    </div>
                </div>

                {/* Bottom: Endpoint Usage */}
                <div className="mt-4 border rounded p-4">
                    <h3 className="text-sm font-semibold mb-2">Endpoint Usage</h3>
                    <p className="text-muted text-xs">Usage analytics placeholder</p>
                </div>
            </SceneContent>
        </BindLogic>
    )
}
