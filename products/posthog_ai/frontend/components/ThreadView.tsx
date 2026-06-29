import { useValues } from 'kea'
import { memo, useCallback, useMemo } from 'react'

import { runStreamLogic } from '../logics/runStreamLogic'
import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import type { ThreadItem } from '../types/streamTypes'
import { getRandomThinkingMessage } from '../utils/thinkingMessages'
import { ContextUsageBar } from './ContextUsageBar'
import { PullRequestCard } from './PullRequestCard'
import { RunContext } from './RunContext'
import { ThreadRow } from './ThreadRow'
import { VirtualizedThread } from './VirtualizedThread'

/** Stable row key — defined at module scope so `getItemKey` never changes identity across renders. */
function getThreadItemKey(item: ThreadItem): string {
    return item.id
}

interface ThreadViewProps {
    /**
     * Pass `false` when an ancestor already owns scroll (the live Max column + auto-scroller) — rows then
     * render in document flow, unchanged from the pre-virtualized layout. Defaults to virtualized.
     */
    virtualized?: boolean
    /**
     * Opts the context-usage line into the footer, shown only between turns (when the agent isn't actively
     * working). Off by default so a bare `ThreadView` is unaffected; the run surface turns it on for live,
     * non-scout runs.
     */
    showContextUsage?: boolean
    className?: string
    listClassName?: string
    rowClassName?: string
}

/**
 * Sandbox-runtime thread presenter. Reads `runStreamLogic.values.threadItems` (assistant text,
 * tool-invocation references, run separators, inline errors) from whatever `runStreamLogic`
 * instance is bound above it — a live PostHog AI conversation or a read-only run viewer — and
 * dispatches tool cards through the sandbox tool registry. Conversation-agnostic by design: it knows
 * only the bound stream logic, never langgraph vs sandbox or the conversation.
 *
 * Rows are virtualized through `VirtualizedThread`, which owns scroll and stick-to-bottom; the leading
 * run context and trailing thinking indicator / PR card / context-usage line ride along as the
 * header/footer rows.
 */
export function ThreadView({
    virtualized = true,
    showContextUsage = false,
    className,
    listClassName,
    rowClassName,
}: ThreadViewProps): JSX.Element {
    const {
        threadItems,
        toolInvocations,
        isThinking,
        streamPhase,
        runArtifacts,
        turnComplete,
        currentRunStatus,
        contextUsage,
    } = useValues(runStreamLogic)
    const turnCancelled = currentRunStatus === 'cancelled'
    const hasActiveProgressItem = threadItems.some(
        (item) => item.type === 'progress' && item.progressSteps?.some((step) => step.status === 'in_progress')
    )

    // Header/footer are kept as memoized leaf components with stable element identity so they don't rebuild
    // `VirtualizedThread`'s `renderRow` (and re-sweep visible rows) on every streamed frame. Each is wrapped
    // in `VirtualizedThread.Row` like the item rows so it gets react-window positioning + height measurement.
    const { branch, baseBranch, repo } = runArtifacts
    const header = useMemo(
        () =>
            branch ? (
                <VirtualizedThread.Row className={rowClassName}>
                    <ThreadHeader branch={branch} baseBranch={baseBranch} repo={repo} />
                </VirtualizedThread.Row>
            ) : undefined,
        [branch, baseBranch, repo]
    )

    const showThinking = streamPhase === 'thinking' && !hasActiveProgressItem
    // Post-turn only: a reconnect refetch can fold in a pr_url mid-run, so gate on !isThinking.
    const pullRequestUrl = !isThinking ? runArtifacts.prUrl : undefined
    // Context usage rides the thread footer, but only between turns (idle) — never while the agent is
    // working, where the thinking line takes the footer. `ContextUsageBar` self-hides without data.
    const showContextUsageFooter = showContextUsage && !isThinking && !!contextUsage
    const footer = useMemo(
        () =>
            showThinking || pullRequestUrl || showContextUsageFooter ? (
                <VirtualizedThread.Row className={rowClassName}>
                    <ThreadFooter
                        showThinking={showThinking}
                        pullRequestUrl={pullRequestUrl}
                        prBranch={branch}
                        showContextUsage={showContextUsageFooter}
                    />
                </VirtualizedThread.Row>
            ) : undefined,
        [showThinking, pullRequestUrl, branch, showContextUsageFooter]
    )

    const renderItem = useCallback(
        (item: ThreadItem, index: number): JSX.Element => (
            <VirtualizedThread.Row className={rowClassName}>
                <ThreadRow
                    item={item}
                    isLast={index === threadItems.length - 1}
                    isThinking={isThinking}
                    toolInvocations={toolInvocations}
                    turnComplete={turnComplete}
                    turnCancelled={turnCancelled}
                />
            </VirtualizedThread.Row>
        ),
        [threadItems.length, isThinking, toolInvocations, turnComplete, turnCancelled, rowClassName]
    )

    return (
        <VirtualizedThread.Root
            items={threadItems}
            getItemKey={getThreadItemKey}
            header={header}
            footer={footer}
            stickToBottom
            virtualized={virtualized}
            className={className}
            listClassName={listClassName}
        >
            {renderItem}
        </VirtualizedThread.Root>
    )
}

/** Leading run-context row. Memoized so it only re-renders when the run's branch/repo refs change. */
const ThreadHeader = memo(function ThreadHeader({
    branch,
    baseBranch,
    repo,
}: {
    branch: string
    baseBranch?: string
    repo?: string
}): JSX.Element {
    return <RunContext branch={branch} baseBranch={baseBranch} repo={repo} />
})

/**
 * Trailing row: the "what's it doing now" thinking line, the produced PR card, and/or the context-usage
 * line (between turns). Subscribes to `currentProgress` itself so the frequently-updating progress text
 * stays isolated here — it never re-renders `ThreadView` or destabilizes the footer's element identity
 * during streaming.
 */
const ThreadFooter = memo(function ThreadFooter({
    showThinking,
    pullRequestUrl,
    prBranch,
    showContextUsage,
}: {
    showThinking: boolean
    pullRequestUrl?: string
    prBranch?: string
    showContextUsage?: boolean
}): JSX.Element {
    const { currentProgress } = useValues(runStreamLogic)
    // `gap-1.5` matches the thread's inter-row gap (`VirtualizedThread`'s `gap` default) so stacked footer
    // items keep the same vertical rhythm as the thread.
    return (
        <div className="flex flex-col gap-1.5">
            {showThinking && <ThinkingIndicator progress={currentProgress} />}
            {pullRequestUrl && <PullRequestCard prUrl={pullRequestUrl} branch={prBranch} />}
            {showContextUsage && <ContextUsageBar />}
        </div>
    )
})

/**
 * Bottom-of-thread "what's it doing right now" line for sandbox conversations. Reflects the latest
 * `_posthog/progress` message when present, otherwise the canned thinking rotation.
 */
function ThinkingIndicator({ progress }: { progress: string | null }): JSX.Element {
    // One roll per mount — re-rolling on every progress transition would visibly swap the verb.
    const fallbackMessage = useMemo(() => getRandomThinkingMessage(), [])
    const message = progress?.trim() ? progress : fallbackMessage
    // Match the LangGraph loader: a bubble-free reasoning line (muted brain icon + muted text),
    // static (no shimmer), via the shared Activity primitive — not a MessageTemplate bubble.
    return <ReasoningAnswer content={message} id="sandbox-thinking" completed={false} showCompletionIcon={false} />
}
