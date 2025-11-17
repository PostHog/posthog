import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { HogQLQuery, Node } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'

import { endpointLogic } from './endpointLogic'
import { endpointSceneLogic } from './endpointSceneLogic'

interface EndpointQueryProps {
    tabId: string
}

export function EndpointQuery({ tabId }: EndpointQueryProps): JSX.Element {
    const { endpoint } = useValues(endpointLogic({ tabId }))
    const { queryToRender } = useValues(endpointSceneLogic({ tabId }))
    const { setLocalQuery } = useActions(endpointSceneLogic({ tabId }))
    const { newTab } = useActions(sceneLogic)

    if (!endpoint || !queryToRender) {
        return <div>No query available</div>
    }

    const handleQueryChange = (query: Node): void => {
        setLocalQuery(query)
    }

    // If it's a HogQL query, show the code editor
    if (isHogQLQuery(endpoint.query)) {
        const hogqlQuery = endpoint.query as HogQLQuery
        const variables = hogqlQuery.variables || {}

        const handleEditQuery = (): void => {
            newTab(urls.sqlEditor(hogqlQuery.query))
        }

        return (
            <div className="flex gap-4">
                <div className="flex-1 flex flex-col gap-2">
                    <CodeEditor value={hogqlQuery.query} language="hogQL" height="300px" options={{ readOnly: true }} />
                    <div>
                        <LemonButton type="secondary" onClick={handleEditQuery} sideIcon={<IconOpenInNew />}>
                            Edit query in SQL Editor
                        </LemonButton>
                    </div>
                </div>
                <div className="w-80 flex-shrink-0">
                    <div className="border rounded p-4">
                        <h3 className="text-sm font-semibold mb-2">Variables (JSON)</h3>
                        <pre className="text-xs overflow-auto">{JSON.stringify(variables, null, 2)}</pre>
                    </div>
                </div>
            </div>
        )
    }

    // For other query types (Insights), show the Query component with editing enabled
    return (
        <div>
            <Query
                query={queryToRender}
                editMode={true}
                setQuery={handleQueryChange}
                context={{ showOpenEditorButton: false }}
            />
        </div>
    )
}
