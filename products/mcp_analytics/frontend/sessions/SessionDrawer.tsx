import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconArrowUpRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MCPDetailDrawer, type MCPDetailDrawerPosition } from '../components/MCPDetailDrawer'
import type { MCPToolCallApi } from '../generated/api.schemas'
import { pickSharedFilterParams } from '../mcpAnalyticsFiltersLogic'
import { mcpSessionUrl } from '../sessionUrls'
import { MCPSessionView } from './MCPSessionView'
import { MCPSessionViewSkeleton } from './MCPSessionViewSkeleton'
import { SessionCallDrawer } from './SessionCallDrawer'
import { sessionCallDrawerLogic } from './sessionCallDrawerLogic'
import { toolCallSessionLogic } from './toolCallSessionLogic'

function SessionTimeline({
    focusedEventId,
    focusedReport,
    onOpenToolCall,
}: {
    focusedEventId: string
    focusedReport?: string
    onOpenToolCall: (toolCall: MCPToolCallApi, toolCalls: MCPToolCallApi[]) => void
}): JSX.Element {
    const { session, toolCalls, intent, generatedIntentLoading, loadedLoading, loadFailed } =
        useValues(toolCallSessionLogic)
    const { loadSession, loadMoreToolCalls, generateIntent } = useActions(toolCallSessionLogic)

    if (!session) {
        return loadedLoading ? (
            <MCPSessionViewSkeleton />
        ) : (
            <div className="mx-3 flex flex-col items-start gap-2 text-sm text-secondary">
                {loadFailed ? 'Could not load this session.' : "This session doesn't match the current filters."}
                {loadFailed ? (
                    <LemonButton size="small" type="secondary" onClick={loadSession}>
                        Retry
                    </LemonButton>
                ) : null}
            </div>
        )
    }
    return (
        <MCPSessionView
            session={session}
            toolCalls={toolCalls}
            intent={intent}
            isGeneratingIntent={generatedIntentLoading}
            onGenerateIntent={generateIntent}
            onLoadMoreToolCalls={loadMoreToolCalls}
            onRetryToolCalls={loadSession}
            focusedEventId={focusedEventId}
            focusedReport={focusedReport}
            onOpenToolCall={onOpenToolCall}
        />
    )
}

/** A session in a drawer with one call or report in focus. Its calls open in a drawer on top. */
export function SessionDrawer({
    sessionId,
    timestamp,
    focusedEventId = '',
    focusedReport,
    noun = 'session',
    position = null,
    onPrevious = null,
    onNext = null,
    stacked = false,
    onClose,
    dataAttr,
}: {
    sessionId: string | null
    timestamp: string
    focusedEventId?: string
    focusedReport?: string
    noun?: string
    position?: MCPDetailDrawerPosition | null
    onPrevious?: (() => void) | null
    onNext?: (() => void) | null
    stacked?: boolean
    onClose: () => void
    dataAttr: string
}): JSX.Element {
    const { searchParams } = useValues(router)
    const { openCall, close: closeCallDrawer } = useActions(sessionCallDrawerLogic)

    // A call from another session would sit over a timeline it does not belong to.
    useEffect(() => closeCallDrawer, [sessionId, focusedEventId, focusedReport, closeCallDrawer])

    return (
        <>
            <MCPDetailDrawer
                noun={noun}
                title="Session"
                position={position}
                onPrevious={onPrevious}
                onNext={onNext}
                fullPageHref={sessionId ? mcpSessionUrl(sessionId, pickSharedFilterParams(searchParams)) : ''}
                fullPageLabel="Open in Sessions"
                fullPageIcon={<IconArrowUpRight />}
                stacked={stacked}
                onClose={onClose}
                data-attr={dataAttr}
            >
                {sessionId ? (
                    <BindLogic logic={toolCallSessionLogic} props={{ sessionId, timestamp }}>
                        <div className="flex h-[calc(100dvh-8rem)] min-h-0 flex-col">
                            <div className="min-h-0 flex-1">
                                <SessionTimeline
                                    focusedEventId={focusedEventId}
                                    focusedReport={focusedReport}
                                    onOpenToolCall={openCall}
                                />
                            </div>
                        </div>
                    </BindLogic>
                ) : (
                    <div className="text-sm text-secondary">This isn't linked to a session.</div>
                )}
            </MCPDetailDrawer>
            <SessionCallDrawer stacked />
        </>
    )
}
