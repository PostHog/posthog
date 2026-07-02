import { useValues } from 'kea'
import { memo, useCallback, useEffect, useMemo, useState } from 'react'

import { inStorybookTestRunner } from 'lib/utils/dom'

import { runStreamLogic } from '../logics/runStreamLogic'
import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import type { ThreadItem } from '../types/streamTypes'
import { getRandomThinkingMessage } from '../utils/thinkingMessages'
import { ContextUsageBar } from './ContextUsageBar'
import { PullRequestCard } from './PullRequestCard'
import { RunAlertActivity } from './RunAlertActivity'
import { RunContext } from './RunContext'
import { ThreadRow } from './ThreadRow'
import { VirtualizedThread } from './VirtualizedThread'

/** Stable row key — defined at module scope so `getItemKey` never changes identity across renders. */
function getThreadItemKey(item: ThreadItem): string {
    return item.id
}

/**
 * Typical rendered height per item type (px, gap excluded). These seed the virtualizer before a row is
 * first measured; the closer they sit to reality, the less the scroll position has to be corrected while
 * scrolling up through unvisited rows — which is what reads as drag/jumping. Rough is fine, order of
 * magnitude matters: a collapsed tool card is ~2 lines, a markdown message is a paragraph or more.
 */
const THREAD_ITEM_HEIGHT_ESTIMATES: Partial<Record<ThreadItem['type'], number>> = {
    human_message: 76,
    assistant_message: 140,
    assistant_thought: 28,
    tool_invocation: 44,
    turn_separator: 24,
    error: 48,
    status: 32,
    compact_boundary: 32,
    task_notification: 40,
    progress: 44,
    debug: 32,
}

function estimateThreadItemHeight(item: ThreadItem): number {
    return THREAD_ITEM_HEIGHT_ESTIMATES[item.type] ?? 56
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
        runConnectionState,
    } = useValues(runStreamLogic)
    const turnCancelled = currentRunStatus === 'cancelled'
    // The last human message anchors the thread. Reopening a saved conversation lands on it — the last
    // meaningful turn, response below — rather than the absolute bottom; a fresh send (the key changing)
    // pins it to the top of the viewport with space reserved below for the streaming response.
    const anchorItemKey = useMemo(
        () => threadItems.findLast((item) => item.type === 'human_message')?.id ?? null,
        [threadItems]
    )
    const hasActiveProgressItem = threadItems.some(
        (item) => item.type === 'progress' && item.progressSteps?.some((step) => step.status === 'in_progress')
    )

    // Header/footer are kept as memoized leaf components with stable element identity so they don't rebuild
    // `VirtualizedThread`'s `renderRow` (and re-sweep visible rows) on every streamed frame. Each is wrapped
    // in `VirtualizedThread.Row` like the item rows so it gets virtualized positioning + height measurement.
    const { branch, baseBranch, repo } = runArtifacts
    const header = useMemo(
        () =>
            branch ? (
                <VirtualizedThread.Row className={rowClassName}>
                    <ThreadHeader branch={branch} baseBranch={baseBranch} repo={repo} />
                </VirtualizedThread.Row>
            ) : undefined,
        [branch, baseBranch, repo, rowClassName]
    )

    // The connection banner (reconnecting / connection-failed) owns the footer line when present, so it
    // takes precedence over the thinking indicator (a mid-run reconnect otherwise reads as normal thinking).
    const showConnectionStatus = !!runConnectionState
    // `provisioning` (conversations/open POST + cold boot before run_started) also shows the indicator,
    // gated by !hasActiveProgressItem so real `_posthog/progress` boot steps take precedence.
    const showThinking =
        (streamPhase === 'thinking' || streamPhase === 'provisioning') &&
        !hasActiveProgressItem &&
        !showConnectionStatus
    const thinkingPhase = streamPhase === 'provisioning' ? 'provisioning' : 'thinking'
    // Post-turn only: a reconnect refetch can fold in a pr_url mid-run, so gate on !isThinking.
    const pullRequestUrl = !isThinking ? runArtifacts.prUrl : undefined
    // Context usage rides the thread footer, but only between turns (idle) — never while the agent is
    // working, where the thinking line takes the footer. `ContextUsageBar` self-hides without data.
    const showContextUsageFooter = showContextUsage && !isThinking && !!contextUsage
    const footer = useMemo(
        () =>
            showThinking || pullRequestUrl || showContextUsageFooter || showConnectionStatus ? (
                <VirtualizedThread.Row className={rowClassName}>
                    <ThreadFooter
                        showThinking={showThinking}
                        thinkingPhase={thinkingPhase}
                        pullRequestUrl={pullRequestUrl}
                        prBranch={branch}
                        showContextUsage={showContextUsageFooter}
                        showConnectionStatus={showConnectionStatus}
                    />
                </VirtualizedThread.Row>
            ) : undefined,
        [
            showThinking,
            thinkingPhase,
            pullRequestUrl,
            branch,
            showContextUsageFooter,
            showConnectionStatus,
            rowClassName,
        ]
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
            estimateItemHeight={estimateThreadItemHeight}
            anchorItemKey={anchorItemKey}
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
    thinkingPhase,
    pullRequestUrl,
    prBranch,
    showContextUsage,
    showConnectionStatus,
}: {
    showThinking: boolean
    thinkingPhase: 'thinking' | 'provisioning'
    pullRequestUrl?: string
    prBranch?: string
    showContextUsage?: boolean
    showConnectionStatus?: boolean
}): JSX.Element {
    // `runConnectionState` is self-subscribed here (like `currentProgress`) so the frequently-updating
    // reconnect attempt counter stays isolated to this leaf and never destabilizes `ThreadView`'s footer.
    const { currentProgress, runConnectionState } = useValues(runStreamLogic)
    // `gap-1.5` matches the thread's inter-row gap (`VirtualizedThread`'s `gap` default) so stacked footer
    // items keep the same vertical rhythm as the thread.
    return (
        <div className="flex flex-col gap-1.5">
            {showConnectionStatus && runConnectionState && <RunAlertActivity {...runConnectionState} />}
            {showThinking && <ThinkingIndicator progress={currentProgress} phase={thinkingPhase} />}
            {pullRequestUrl && <PullRequestCard prUrl={pullRequestUrl} branch={prBranch} />}
            {showContextUsage && <ContextUsageBar />}
        </div>
    )
})

/**
 * Bottom-of-thread "what's it doing right now" line for sandbox conversations. Reflects the latest
 * `_posthog/progress` message when present; during `provisioning` (the conversations/open POST / cold
 * boot before `run_started`) it shows a fixed "spinning up" message, otherwise the canned thinking rotation.
 */
function ThinkingIndicator({
    progress,
    phase,
}: {
    progress: string | null
    phase: 'thinking' | 'provisioning'
}): JSX.Element {
    const [fallbackMessage, setFallbackMessage] = useState(() => getRandomThinkingMessage())

    // Re-roll the gerund every 5s while genuinely thinking; static "Spinning up sandbox…" during provisioning
    // doesn't need it, and rotating in Storybook would make snapshots non-deterministic.
    useEffect(() => {
        if (phase !== 'thinking' || inStorybookTestRunner()) {
            return
        }
        const interval = setInterval(() => setFallbackMessage(getRandomThinkingMessage()), 5000)
        return () => clearInterval(interval)
    }, [phase])

    const message = progress?.trim() ? progress : phase === 'provisioning' ? 'Setting up sandbox' : fallbackMessage
    // Match the LangGraph loader: a bubble-free reasoning line (muted brain icon + muted text), via the
    // shared Activity primitive — not a MessageTemplate bubble. Shimmers only while genuinely thinking;
    // provisioning stays static since it's infra boot, not model reasoning.
    return (
        <ReasoningAnswer
            content={message}
            id="sandbox-thinking"
            completed={false}
            showCompletionIcon={false}
            animate={phase === 'thinking' || phase === 'provisioning'}
        />
    )
}
