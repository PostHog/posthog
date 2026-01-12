import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { HogQLQuery, HogQLVariable, Node } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'

import { endpointLogic } from '../endpointLogic'
import { endpointSceneLogic } from '../endpointSceneLogic'

function formatVariableValue(variable: HogQLVariable): { text: string; isPlaceholder: boolean } {
    if (variable.value === undefined || variable.value === null || variable.value === '') {
        return { text: 'null', isPlaceholder: true }
    }
    if (typeof variable.value === 'object') {
        return { text: JSON.stringify(variable.value), isPlaceholder: false }
    }
    return { text: String(variable.value), isPlaceholder: false }
}

interface EndpointQueryProps {
    tabId: string
}

export function EndpointQuery({ tabId }: EndpointQueryProps): JSX.Element {
    const { endpoint } = useValues(endpointLogic({ tabId }))
    const { queryToRender, endpointLoading } = useValues(endpointSceneLogic({ tabId }))
    const { setLocalQuery } = useActions(endpointSceneLogic({ tabId }))
    const { newTab } = useActions(sceneLogic)

    if (endpointLoading) {
        return (
            <div className="flex items-center justify-center h-60">
                <Spinner />
            </div>
        )
    }

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
            newTab(urls.sqlEditor(hogqlQuery.query, undefined, undefined, undefined, OutputTab.Endpoint, endpoint.name))
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
                {Object.keys(variables).length > 0 && (
                    <div className="w-80 flex-shrink-0">
                        <div className="border rounded p-4">
                            <h3 className="text-sm font-semibold mb-3">Variable default values</h3>
                            <div className="flex flex-col gap-3">
                                {Object.values(variables).map((variable) => {
                                    const { text, isPlaceholder } = formatVariableValue(variable)
                                    return (
                                        <LemonField.Pure key={variable.variableId} label={variable.code_name}>
                                            <div
                                                className={`text-sm border rounded px-2 py-1 ${
                                                    isPlaceholder ? 'text-muted italic' : 'font-mono bg-bg-light'
                                                }`}
                                            >
                                                {text}
                                            </div>
                                        </LemonField.Pure>
                                    )
                                })}
                            </div>
                        </div>
                    </div>
                )}
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
