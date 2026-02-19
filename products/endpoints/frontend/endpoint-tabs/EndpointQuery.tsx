import { useActions, useValues } from 'kea'
import { MouseEvent as ReactMouseEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { HogQLQuery, HogQLVariable, Node, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

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
    const { queryToRender, endpointLoading, viewingVersion } = useValues(endpointSceneLogic({ tabId }))
    const { setLocalQuery } = useActions(endpointSceneLogic({ tabId }))
    // Use the query from the viewed version if set, otherwise fall back to endpoint
    const effectiveQuery = viewingVersion?.query || endpoint?.query

    if (endpointLoading && !endpoint) {
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

    // If it's a HogQL query, show the embedded SQL editor with results
    if (effectiveQuery && isHogQLQuery(effectiveQuery)) {
        const hogqlQuery = effectiveQuery as HogQLQuery
        return <EndpointHogQLQuery tabId={tabId} version={viewingVersion?.version} query={hogqlQuery} />
    }

    // For other query types (Insights), show the Query component with editing enabled
    const queryKey = viewingVersion?.version ?? 'current'

    return (
        <div>
            <Query
                key={queryKey}
                query={queryToRender}
                editMode={true}
                setQuery={handleQueryChange}
                context={{ showOpenEditorButton: false }}
            />
        </div>
    )
}

function EndpointHogQLQuery({
    tabId,
    version,
    query,
}: {
    tabId: string
    version?: number
    query: HogQLQuery
}): JSX.Element {
    const variables = query.variables || {}
    const sqlEditorTabId = useMemo(() => `endpoint-query-${tabId}-${version ?? 'latest'}`, [tabId, version])
    const { setLocalQuery } = useActions(endpointSceneLogic({ tabId }))
    const { queryInput } = useValues(sqlEditorLogic({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded }))
    const { setQueryInput, setSourceQuery, runQuery } = useActions(
        sqlEditorLogic({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded })
    )

    useEffect(() => {
        setQueryInput(query.query)
        setSourceQuery({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: query.query,
                variables: query.variables,
            },
            display: ChartDisplayType.ActionsLineGraph,
        })
        runQuery(query.query)
    }, [query.query, query.variables]) // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (queryInput === query.query) {
            setLocalQuery(null)
            return
        }

        setLocalQuery({
            kind: NodeKind.HogQLQuery,
            query: queryInput,
            variables: query.variables,
        } as HogQLQuery)
    }, [query.query, query.variables, queryInput]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex gap-4">
            <div className="flex-1 flex flex-col gap-2">
                <ResizableSQLEditorContainer>
                    <SQLEditor tabId={sqlEditorTabId} mode={SQLEditorMode.Embedded} />
                </ResizableSQLEditorContainer>
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
                                        <div className="flex items-center gap-1">
                                            <div
                                                className={`text-sm border rounded px-2 py-1 flex-1 ${
                                                    isPlaceholder ? 'text-muted italic' : 'font-mono bg-bg-light'
                                                }`}
                                            >
                                                {text}
                                            </div>
                                            <LemonButton
                                                icon={<IconPencil />}
                                                size="small"
                                                type="tertiary"
                                                to={urls.variableEdit(variable.variableId)}
                                                tooltip="Edit variable"
                                            />
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

const DEFAULT_EDITOR_HEIGHT = 608
const MIN_EDITOR_HEIGHT = 384

function ResizableSQLEditorContainer({ children }: { children: ReactNode }): JSX.Element {
    const [height, setHeight] = useState(DEFAULT_EDITOR_HEIGHT)
    const containerRef = useRef<HTMLDivElement | null>(null)

    const startResizing = (event: ReactMouseEvent, startHeight: number): void => {
        event.preventDefault()
        const startY = event.clientY

        const onMouseMove = (moveEvent: MouseEvent): void => {
            setHeight(Math.max(MIN_EDITOR_HEIGHT, startHeight + (moveEvent.clientY - startY)))
        }

        const onMouseUp = (): void => {
            window.removeEventListener('mousemove', onMouseMove)
            window.removeEventListener('mouseup', onMouseUp)
        }

        window.addEventListener('mousemove', onMouseMove)
        window.addEventListener('mouseup', onMouseUp)
    }

    return (
        <div ref={containerRef} className="relative border rounded overflow-hidden" style={{ height }}>
            {children}
            <div
                className="absolute bottom-0 left-0 h-2 w-full cursor-s-resize"
                onMouseDown={(event) => {
                    startResizing(event, containerRef.current?.clientHeight ?? height)
                }}
            />
            <div
                className="absolute bottom-0 right-0 z-10 h-5 w-5 cursor-se-resize"
                onMouseDown={(event) => {
                    startResizing(event, containerRef.current?.clientHeight ?? height)
                }}
            />
        </div>
    )
}
