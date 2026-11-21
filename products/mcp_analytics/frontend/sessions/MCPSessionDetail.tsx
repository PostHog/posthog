import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { mcpSessionsLogic } from './mcpSessionsLogic'
import { MCPSessionView } from './MCPSessionView'
import { MCPSessionViewSkeleton } from './MCPSessionViewSkeleton'
import { SessionCallDrawer } from './SessionCallDrawer'
import { sessionCallDrawerLogic } from './sessionCallDrawerLogic'

export function MCPSessionDetail({ stacked = false }: { stacked?: boolean }): JSX.Element {
    const {
        selectedSession,
        selectedSessionToolCalls,
        selectedSessionIntent,
        isSelectedSessionGenerating,
        sessionsLoading,
    } = useValues(mcpSessionsLogic)
    const { generateIntent, loadMoreToolCalls, loadToolCalls } = useActions(mcpSessionsLogic)
    const { openCall, close: closeCallDrawer } = useActions(sessionCallDrawerLogic)
    const selectedSessionId = selectedSession?.session_id

    // A call from the previous session would sit over a timeline it does not belong to.
    useEffect(() => closeCallDrawer, [selectedSessionId, closeCallDrawer])

    if (!selectedSession) {
        if (sessionsLoading) {
            return <MCPSessionViewSkeleton />
        }
        return (
            <div className="flex h-full items-center justify-center text-sm text-secondary p-6 text-center">
                Pick a session to step through its tool calls.
            </div>
        )
    }

    const sessionId = selectedSession.session_id
    return (
        <>
            <MCPSessionView
                session={selectedSession}
                toolCalls={selectedSessionToolCalls}
                intent={selectedSessionIntent}
                isGeneratingIntent={isSelectedSessionGenerating}
                onGenerateIntent={() => generateIntent(sessionId)}
                onLoadMoreToolCalls={() => loadMoreToolCalls(sessionId)}
                onRetryToolCalls={() => loadToolCalls(sessionId)}
                onOpenToolCall={openCall}
            />
            <SessionCallDrawer stacked={stacked} />
        </>
    )
}
