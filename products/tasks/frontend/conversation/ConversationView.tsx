import { JSX, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import type { AcpMessage, QueuedMessage } from './acp-types'
import type { ConversationItem, TurnContext } from './buildConversationItems'
import { GeneratingIndicator } from './GeneratingIndicator'
import { GitActionMessage } from './GitActionMessage'
import { GitActionResult } from './GitActionResult'
import { mergeConversationItems } from './mergeConversationItems'
import { QueuedMessageView } from './messages/QueuedMessageView'
import { UserMessage } from './messages/UserMessage'
import { UserShellExecuteView } from './messages/UserShellExecuteView'
import { IconArrowRightDown, IconX } from './primitives/icons'
import { SessionFooter } from './SessionFooter'
import { type RenderItem, SessionUpdateView } from './SessionUpdateView'
import { useConversationItems } from './useConversationItems'

interface ConversationViewProps {
    events: AcpMessage[]
    isPromptPending?: boolean | null
    promptStartedAt?: number | null
    queuedMessages?: QueuedMessage[]
    /** Optimistically-rendered user messages awaiting their streamed echo. */
    optimisticItems?: ConversationItem[]
    showDebugLogs?: boolean
    isCloud?: boolean
    className?: string
}

/**
 * Read-only port of PostHog Code's `ConversationView`. Builds conversation items
 * from raw ACP events and renders them as a plain, scrollable transcript. There
 * is no input composer, no live git / tRPC / MCP host and no editor links — the
 * live affordances are rendered statically or disabled by the underlying views.
 */
export const ConversationView = memo(function ConversationView({
    events,
    isPromptPending = null,
    promptStartedAt,
    queuedMessages,
    optimisticItems,
    showDebugLogs,
    isCloud = false,
    className,
}: ConversationViewProps): JSX.Element {
    const {
        items: conversationItems,
        lastTurnInfo,
        isCompacting,
    } = useConversationItems(events, isPromptPending, { showDebugLogs })

    const queuedItems = useMemo<Extract<ConversationItem, { type: 'queued' }>[]>(
        () =>
            (queuedMessages ?? []).map((message) => ({
                type: 'queued' as const,
                id: message.id,
                message,
            })),
        [queuedMessages]
    )

    const items = useMemo<ConversationItem[]>(
        () =>
            queuedItems.length > 0 || (optimisticItems?.length ?? 0) > 0
                ? mergeConversationItems({
                      conversationItems,
                      optimisticItems: optimisticItems ?? [],
                      queuedItems,
                      isCloud,
                  })
                : conversationItems,
        [conversationItems, queuedItems, optimisticItems, isCloud]
    )

    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const bottomRef = useRef<HTMLDivElement>(null)
    const isPinnedRef = useRef(true)
    const [showScrollButton, setShowScrollButton] = useState(false)

    const scrollToBottom = useCallback(() => {
        bottomRef.current?.scrollIntoView({ block: 'end' })
        isPinnedRef.current = true
        setShowScrollButton(false)
    }, [])

    const handleScroll = useCallback(() => {
        const el = scrollContainerRef.current
        if (!el) {
            return
        }
        const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
        const pinned = distanceFromBottom < 64
        isPinnedRef.current = pinned
        setShowScrollButton(!pinned)
    }, [])

    // Keep the view pinned to the bottom as new items stream in, unless the user
    // has scrolled up to read earlier output.
    useEffect(() => {
        if (isPinnedRef.current) {
            bottomRef.current?.scrollIntoView({ block: 'end' })
        }
    }, [items.length])

    const isPending = !!isPromptPending
    const showFooter = isPending || (lastTurnInfo?.isComplete ?? false) || isCompacting

    return (
        <div className={`group/thread relative flex h-full flex-col ${className ?? ''}`}>
            <div
                ref={scrollContainerRef}
                onScroll={handleScroll}
                className="flex-1 overflow-auto bg-bg-3000 px-2 py-1.5"
            >
                {items.map((item) => (
                    <div key={item.id} className="mx-auto max-w-4xl px-2 py-1.5">
                        <ConversationItemRow item={item} />
                    </div>
                ))}
                {showFooter && (
                    <div className="mx-auto max-w-4xl px-2 pb-4">
                        <SessionFooter
                            isPromptPending={isPromptPending}
                            promptStartedAt={promptStartedAt}
                            lastGenerationDuration={
                                lastTurnInfo?.isComplete ? Math.max(0, lastTurnInfo.durationMs) : null
                            }
                            lastStopReason={lastTurnInfo?.stopReason}
                            queuedCount={queuedItems.length}
                            isCompacting={isCompacting}
                        />
                    </div>
                )}
                {isPending && !showFooter && (
                    <div className="mx-auto max-w-4xl px-2 pb-4">
                        <GeneratingIndicator startedAt={promptStartedAt} />
                    </div>
                )}
                <div ref={bottomRef} />
            </div>
            {showScrollButton && (
                <div className="absolute right-6 bottom-4 z-10">
                    <Tooltip title="Scroll to bottom">
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconArrowRightDown />}
                            onClick={scrollToBottom}
                        />
                    </Tooltip>
                </div>
            )}
        </div>
    )
})

const ConversationItemRow = memo(function ConversationItemRow({
    item,
}: {
    item: ConversationItem
}): JSX.Element | null {
    switch (item.type) {
        case 'user_message':
            return <UserMessage content={item.content} attachments={item.attachments} timestamp={item.timestamp} />
        case 'git_action':
            return <GitActionMessage actionType={item.actionType} />
        case 'git_action_result':
            return <GitActionResult actionType={item.actionType} />
        case 'skill_button_action':
            return <span className="text-[13px] text-muted">Skill action</span>
        case 'session_update':
            return (
                <SessionUpdateRow
                    update={item.update}
                    turnContext={item.turnContext}
                    thoughtComplete={item.thoughtComplete}
                />
            )
        case 'turn_cancelled':
            return <TurnCancelledView interruptReason={item.interruptReason} />
        case 'user_shell_execute':
            return <UserShellExecuteView item={item} />
        case 'queued':
            return <QueuedMessageView message={item.message} />
        default:
            return null
    }
})

const SessionUpdateRow = memo(function SessionUpdateRow({
    update,
    turnContext,
    thoughtComplete,
}: {
    update: RenderItem
    turnContext: TurnContext
    thoughtComplete?: boolean
}): JSX.Element | null {
    return (
        <SessionUpdateView
            item={update}
            toolCalls={turnContext.toolCalls}
            childItems={turnContext.childItems}
            turnCancelled={turnContext.turnCancelled}
            turnComplete={turnContext.turnComplete}
            thoughtComplete={thoughtComplete}
        />
    )
})

const TurnCancelledView = memo(function TurnCancelledView({
    interruptReason,
}: {
    interruptReason?: string
}): JSX.Element {
    const message =
        interruptReason === 'moving_to_worktree' ? 'Paused while worktree is focused' : 'Interrupted by user'

    return (
        <div className="border-l-2 border-border py-0.5 pl-3">
            <div className="flex items-center gap-2 text-muted">
                <IconX style={{ fontSize: 14 }} />
                <span className="text-[13px] text-muted">{message}</span>
            </div>
        </div>
    )
})
