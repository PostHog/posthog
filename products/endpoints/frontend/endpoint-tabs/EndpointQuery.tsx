import { useActions, useValues } from 'kea'
import { MouseEvent as ReactMouseEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'

import { endpointLogic } from '../endpointLogic'
import { endpointSceneLogic } from '../endpointSceneLogic'

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
        return <EndpointHogQLQuery tabId={tabId} version={viewingVersion?.version} />
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

function EndpointHogQLQuery({ tabId, version }: { tabId: string; version?: number }): JSX.Element {
    const sqlEditorTabId = useMemo(() => `endpoint-query-${tabId}-${version ?? 'latest'}`, [tabId, version])
    const { keepSqlEditorMounted } = useActions(endpointSceneLogic({ tabId }))

    useEffect(() => {
        // Hand off the editor lifecycle to endpointSceneLogic: it mounts/unmounts sqlEditorLogic,
        // seeds it with the stored query on first mount, and bridges its state into localQuery.
        keepSqlEditorMounted(sqlEditorTabId)
    }, [sqlEditorTabId]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex min-w-0 gap-4">
            <div className="flex min-w-0 flex-1 flex-col gap-2">
                <ResizableSQLEditorContainer>
                    <SQLEditor tabId={sqlEditorTabId} mode={SQLEditorMode.Embedded} defaultShowDatabaseTree={false} />
                </ResizableSQLEditorContainer>
            </div>
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
