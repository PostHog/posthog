import { useValues } from 'kea'
import { memo, useCallback, useMemo } from 'react'

import { runStreamLogic } from '../logics/runStreamLogic'
import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import type { ThreadItem } from '../types/streamTypes'
import { getRandomThinkingMessage } from '../utils/thinkingMessages'
import { PullRequestCard } from './PullRequestCard'
import { RunContext } from './RunContext'
import { ThreadRow } from './ThreadRow'
import { VirtualizedThread } from './VirtualizedThread'

/** Stable row key — defined at module scope so `getItemKey` never changes identity across renders. */
function getThreadItemKey(item: ThreadItem): string {
    return item.id
}

/**
 * Sandbox-runtime thread presenter. Reads `runStreamLogic.values.threadItems` (assistant text,
 * tool-invocation references, run separators, inline errors) from whatever `runStreamLogic`
 * instance is bound above it — a live PostHog AI conversation or a read-only run viewer — and
 * dispatches tool cards through the sandbox tool registry. Conversation-agnostic by design: it knows
 * only the bound stream logic, never langgraph vs sandbox or the conversation.
 *
 * Rows are virtualized through `VirtualizedThread`, which owns scroll and stick-to-bottom; the leading
 * run context and trailing thinking indicator / PR card ride along as the header/footer rows. Pass
 * `virtualized={false}` when an ancestor already owns scroll (the live Max column + auto-scroller) — rows
 * then render in document flow, unchanged from the pre-virtualized layout.
 */
export function ThreadView({ virtualized = true }: { virtualized?: boolean } = {}): JSX.Element {
    const { threadItems, toolInvocations, isThinking, streamPhase, runArtifacts, turnComplete, currentRunStatus } =
        useValues(runStreamLogic)
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
                <VirtualizedThread.Row>
                    <ThreadHeader branch={branch} baseBranch={baseBranch} repo={repo} />
                </VirtualizedThread.Row>
            ) : undefined,
        [branch, baseBranch, repo]
    )

    const showThinking = streamPhase === 'thinking' && !hasActiveProgressItem
    // Post-turn only: a reconnect refetch can fold in a pr_url mid-run, so gate on !isThinking.
    const pullRequestUrl = !isThinking ? runArtifacts.prUrl : undefined
    const footer = useMemo(
        () =>
            showThinking || pullRequestUrl ? (
                <VirtualizedThread.Row>
                    <ThreadFooter showThinking={showThinking} pullRequestUrl={pullRequestUrl} prBranch={branch} />
                </VirtualizedThread.Row>
            ) : undefined,
        [showThinking, pullRequestUrl, branch]
    )

    const renderItem = useCallback(
        (item: ThreadItem, index: number): JSX.Element => (
            <VirtualizedThread.Row>
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
        [threadItems.length, isThinking, toolInvocations, turnComplete, turnCancelled]
    )

    return (
        <VirtualizedThread.Root
            items={threadItems}
            getItemKey={getThreadItemKey}
            header={header}
            footer={footer}
            stickToBottom
            virtualized={virtualized}
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
 * Trailing row: the "what's it doing now" thinking line and/or the produced PR card. Subscribes to
 * `currentProgress` itself so the frequently-updating progress text stays isolated here — it never
 * re-renders `ThreadView` or destabilizes the footer's element identity during streaming.
 */
const ThreadFooter = memo(function ThreadFooter({
    showThinking,
    pullRequestUrl,
    prBranch,
}: {
    showThinking: boolean
    pullRequestUrl?: string
    prBranch?: string
}): JSX.Element {
    const { currentProgress } = useValues(runStreamLogic)
    return (
        <>
            {showThinking && <ThinkingIndicator progress={currentProgress} />}
            {pullRequestUrl && <PullRequestCard prUrl={pullRequestUrl} branch={prBranch} />}
        </>
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
