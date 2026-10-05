import { useActions, useValues } from 'kea'
import { type ReactNode, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { cn } from 'lib/utils/css-classes'
import { inStorybookTestRunner } from 'lib/utils/dom'

import { isTerminalRunStatus, runStreamLogic } from '../logics/runStreamLogic'
import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import {
    groupThreadActivity,
    groupToolRuns,
    isRunningStatus,
    isStartupStatus,
    reuseActivityGroups,
    type ThreadActivityGroup as ThreadActivityGroupItem,
    type ThreadDisplayItem,
} from '../utils/groupThreadActivity'
import { getRandomThinkingMessage } from '../utils/thinkingMessages'
import { resolveToolCall } from '../utils/toolResolver'
import { TurnHoverStore } from '../utils/turnHoverStore'
import { type TurnTrailer, computeTurnTrailers, mapRowsToRevealGroup } from '../utils/turnTrailers'
import { ContextUsageChip } from './ContextUsageChip'
import { PullRequestCard } from './PullRequestCard'
import { type ThreadSkin, ThreadSkinContext } from './quill/quillThreadContext'
import { RunAlertActivity } from './RunAlertActivity'
import { RunContext } from './RunContext'
import { ThreadActivityGroup } from './ThreadActivityGroup'
import { ThreadRow, type ThreadRowProps } from './ThreadRow'
import { lookupToolRenderer } from './tool/toolRegistry'
import { TurnReveal } from './TurnReveal'
import { VirtualizedThread } from './VirtualizedThread'

/** Stable row key — defined at module scope so `getItemKey` never changes identity across renders. */
function getThreadRowKey(row: ThreadViewRow): string {
    return row.item.id
}

/**
 * Typical rendered height per item type (px, gap excluded). These seed the virtualizer before a row is
 * first measured; the closer they sit to reality, the less the scroll position has to be corrected while
 * scrolling up through unvisited rows — which is what reads as drag/jumping. Rough is fine, order of
 * magnitude matters: a collapsed tool card is ~2 lines, a markdown message is a paragraph or more.
 */
const THREAD_ITEM_HEIGHT_ESTIMATES: Partial<Record<ThreadItem['type'], number>> = {
    human_message: 160,
    assistant_message: 46,
    assistant_thought: 26,
    tool_invocation: 42,
    turn_separator: 24,
    error: 42,
    status: 42,
    compact_boundary: 42,
    conversation_cleared: 42,
    task_notification: 26,
    progress: 42,
    debug: 30,
}

/** The quill thread leaves a lone call or thought outside a group, and such a row shows its own live state. */
function quillRowShowsProgress(item: ThreadDisplayItem, toolInvocations: ReadonlyMap<string, ToolInvocation>): boolean {
    switch (item.type) {
        case 'assistant_thought':
            // An empty thought renders nothing, so the bottom indicator still has to show.
            return !!item.text?.trim()
        case 'tool_invocation': {
            const status = item.toolCallId ? toolInvocations.get(item.toolCallId)?.status : undefined
            return status === 'pending' || status === 'in_progress'
        }
        case 'status':
            return isStartupStatus(item) || isRunningStatus(item)
        default:
            return false
    }
}

function estimateThreadRowHeight({ item }: ThreadViewRow): number {
    if (item.type === 'activity_group') {
        return 48
    }
    return THREAD_ITEM_HEIGHT_ESTIMATES[item.type] ?? 56
}

interface ThreadViewProps {
    scrollRestorationKey?: string
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
    /** Renders per-turn UI (e.g. feedback actions) at each completed turn's end. */
    renderTurnTrailer?: (trailer: TurnTrailer) => JSX.Element | null
    /** Extra footer content below the thinking / PR / context-usage rows (e.g. the feedback prompt). */
    footerExtra?: ReactNode
    className?: string
    listClassName?: string
    endInset?: number
    rowClassName?: string
    /**
     * `quill` lays the thread out like PostHog Desktop's chat: user bubbles, ghost assistant prose, and
     * each step as a quill chat marker. Every presenter below picks its skin from `ThreadSkinContext`,
     * so tool renderers need no changes.
     */
    skin?: ThreadSkin
}

const QUILL_ROW_GAP = 16

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
    scrollRestorationKey,
    virtualized = true,
    showContextUsage = false,
    renderTurnTrailer,
    footerExtra,
    className,
    listClassName,
    rowClassName,
    endInset,
    skin = 'lemon',
}: ThreadViewProps): JSX.Element {
    const {
        threadItems,
        toolInvocations,
        isThinking,
        streamPhase,
        showThinkingIndicator,
        runArtifacts,
        turnComplete,
        currentRunStatus,
        contextUsage,
        runConnectionState,
        logBootstrapLoading,
        pendingPermissionRequest,
    } = useValues(runStreamLogic)
    const turnCancelled = currentRunStatus === 'cancelled'
    // A replayed error from an earlier run in the chain is not this run's ending while a newer run is
    // still going, so it keeps the softer title.
    const runEnded = isTerminalRunStatus(currentRunStatus)
    const { pinnedToolIds, widgetToolIds } = useMemo(() => {
        const pinned = new Set<string>()
        const widgets = new Set<string>()
        for (const [id, invocation] of toolInvocations) {
            const resolved = resolveToolCall(invocation)
            const entry = lookupToolRenderer(resolved.resolvedKey, !!resolved.innerToolName)
            if (entry.pinned) {
                pinned.add(id)
            } else if (entry.keepVisible) {
                widgets.add(id)
            }
        }
        return { pinnedToolIds: pinned, widgetToolIds: widgets }
    }, [toolInvocations])
    const previousDisplayItems = useRef<ThreadDisplayItem[]>([])
    const displayItems = useMemo(() => {
        const grouped =
            skin === 'quill'
                ? groupToolRuns(threadItems, toolInvocations, { pinnedToolIds, widgetToolIds, settled: !isThinking })
                : groupThreadActivity(threadItems, new Set([...pinnedToolIds, ...widgetToolIds]))
        const reconciled = reuseActivityGroups(previousDisplayItems.current, grouped)
        previousDisplayItems.current = reconciled
        return reconciled
    }, [threadItems, toolInvocations, pinnedToolIds, widgetToolIds, skin, isThinking])
    // The last human message anchors the thread. Reopening a saved conversation lands on it — the last
    // meaningful turn, response below — when at least a viewport of content follows it (otherwise the
    // bottom); a fresh send (a new key) pins the thread to the bottom to follow the streaming response.
    const anchorItemKey = useMemo(
        () => threadItems.findLast((item) => item.type === 'human_message')?.id ?? null,
        [threadItems]
    )
    // Only computed when a trailer renderer is supplied — bare ThreadViews pay nothing.
    const previousTrailers = useRef<Map<string, TurnTrailer> | null>(null)
    const trailers = useMemo(() => {
        const next = renderTurnTrailer
            ? reuseTurnTrailers(previousTrailers.current, computeTurnTrailers(threadItems))
            : null
        previousTrailers.current = next
        return next
    }, [threadItems, renderTurnTrailer])
    const revealGroups = useMemo(() => mapRowsToRevealGroup(displayItems), [displayItems])
    const previousRows = useRef<ThreadViewRow[]>([])
    const rows = useMemo(() => {
        const next = buildThreadViewRows(previousRows.current, displayItems, toolInvocations, trailers, revealGroups)
        previousRows.current = next
        return next
    }, [displayItems, toolInvocations, trailers, revealGroups])
    const [turnHoverStore] = useState(() => new TurnHoverStore())

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
    const lastItem = displayItems.at(-1)
    const lastRowShowsProgress =
        lastItem?.type === 'activity_group' ||
        (skin === 'quill' && !!lastItem && quillRowShowsProgress(lastItem, toolInvocations))
    const showThinking =
        showThinkingIndicator && !showConnectionStatus && !pendingPermissionRequest && !lastRowShowsProgress
    const thinkingPhase = streamPhase === 'provisioning' ? 'provisioning' : 'thinking'
    // Post-turn only: a reconnect refetch can fold in a pr_url mid-run, so gate on !isThinking.
    const pullRequestUrl = !isThinking ? runArtifacts.prUrl : undefined
    // Context usage rides the thread footer, but only between turns (idle) — never while the agent is
    // working, where the thinking line takes the footer. `ContextUsageChip` self-hides without data.
    const showContextUsageFooter = showContextUsage && streamPhase === 'idle' && !!contextUsage
    const footer = useMemo(
        () =>
            showThinking || pullRequestUrl || showContextUsageFooter || showConnectionStatus || footerExtra ? (
                <VirtualizedThread.Row className={rowClassName}>
                    <ThreadFooter
                        showThinking={showThinking}
                        thinkingPhase={thinkingPhase}
                        pullRequestUrl={pullRequestUrl}
                        prBranch={branch}
                        showContextUsage={showContextUsageFooter}
                        showConnectionStatus={showConnectionStatus}
                        extra={footerExtra}
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
            footerExtra,
            rowClassName,
        ]
    )

    const renderItem = useCallback(
        ({ item, isLast, turnId, invocation, groupInvocations, trailer }: ThreadViewRow): JSX.Element => {
            if (item.type === 'activity_group') {
                return (
                    <ActivityGroupRow
                        group={item}
                        rowClassName={rowClassName}
                        turnHoverStore={turnHoverStore}
                        turnId={turnId}
                        toolInvocations={groupInvocations ?? EMPTY_INVOCATIONS}
                        active={isLast && isThinking}
                        waitingForInput={isLast && !!pendingPermissionRequest}
                        cancelled={isLast && (turnCancelled || currentRunStatus === 'failed')}
                        turnComplete={turnComplete}
                        turnCancelled={turnCancelled}
                    />
                )
            }
            if (item.type === 'turn_separator' && renderTurnTrailer) {
                return (
                    <TurnTrailerRow
                        turnId={item.id}
                        trailer={trailer}
                        renderTurnTrailer={renderTurnTrailer}
                        rowClassName={rowClassName}
                        turnHoverStore={turnHoverStore}
                    />
                )
            }
            return (
                <ItemRow
                    item={item}
                    rowClassName={rowClassName}
                    turnHoverStore={turnHoverStore}
                    turnId={turnId}
                    isLast={isLast}
                    isThinking={isThinking}
                    invocation={invocation}
                    turnComplete={turnComplete}
                    turnCancelled={turnCancelled}
                    runEnded={runEnded}
                />
            )
        },
        [
            isThinking,
            turnComplete,
            turnCancelled,
            rowClassName,
            renderTurnTrailer,
            turnHoverStore,
            pendingPermissionRequest,
            currentRunStatus,
            runEnded,
        ]
    )

    const thread = (
        <VirtualizedThread.Root
            key={scrollRestorationKey}
            scrollRestorationKey={scrollRestorationKey}
            items={rows}
            getItemKey={getThreadRowKey}
            estimateItemHeight={estimateThreadRowHeight}
            anchorItemKey={anchorItemKey}
            // The history replay folds in over several commits (debug rows land before the human turns);
            // the opening scroll must wait for the full log or it opens at the bottom of a partial thread.
            itemsLoading={logBootstrapLoading}
            header={header}
            footer={footer}
            stickToBottom
            // Provisioning counts too: the optimistic "spinning up" window is part of the turn, so the
            // thread is already pinned when the first streamed rows land.
            turnActive={streamPhase !== 'idle'}
            virtualized={virtualized}
            endInset={endInset}
            gap={skin === 'quill' ? QUILL_ROW_GAP : undefined}
            className={className}
            listClassName={listClassName}
        >
            {renderItem}
        </VirtualizedThread.Root>
    )
    if (skin === 'lemon') {
        return thread
    }
    return (
        <ThreadSkinContext.Provider value={skin}>
            {/* Virtualized, the root lays out rows itself; in document flow, this wrapper sets the rhythm. */}
            {/* Quill's text color, set once here: a ghost bubble sets none, so its prose would inherit the page's. */}
            <div
                data-quill
                className={cn('text-[var(--foreground)]', virtualized ? 'contents' : 'flex flex-col gap-4')}
            >
                {thread}
            </div>
        </ThreadSkinContext.Provider>
    )
}

function reuseTurnTrailers(
    previous: Map<string, TurnTrailer> | null,
    next: Map<string, TurnTrailer>
): Map<string, TurnTrailer> {
    if (!previous) {
        return next
    }
    for (const [id, trailer] of next) {
        const old = previous.get(id)
        if (
            old &&
            old.turnIndex === trailer.turnIndex &&
            old.isLastTurn === trailer.isLastTurn &&
            old.turnText === trailer.turnText &&
            old.traceId === trailer.traceId &&
            old.timestamp === trailer.timestamp
        ) {
            next.set(id, old)
        }
    }
    return next
}

const EMPTY_INVOCATIONS: Map<string, ToolInvocation> = new Map()

interface ThreadViewRow {
    item: ThreadDisplayItem
    isLast: boolean
    turnId?: string
    invocation?: ToolInvocation
    groupInvocations?: Map<string, ToolInvocation>
    trailer?: TurnTrailer
}

function sameInvocations(a: Map<string, ToolInvocation> | undefined, b: Map<string, ToolInvocation>): boolean {
    if (!a || a.size !== b.size) {
        return false
    }
    for (const [id, invocation] of b) {
        if (a.get(id) !== invocation) {
            return false
        }
    }
    return true
}

function buildThreadViewRows(
    previous: ThreadViewRow[],
    displayItems: ThreadDisplayItem[],
    toolInvocations: Map<string, ToolInvocation>,
    trailers: Map<string, TurnTrailer> | null,
    revealGroups: Map<string, string>
): ThreadViewRow[] {
    const previousById = new Map<string, ThreadViewRow>()
    for (const row of previous) {
        previousById.set(row.item.id, row)
    }
    return displayItems.map((item, index) => {
        const old = previousById.get(item.id)
        let groupInvocations: Map<string, ToolInvocation> | undefined
        if (item.type === 'activity_group') {
            groupInvocations = new Map()
            for (const activity of item.items) {
                const call = activity.toolCallId ? toolInvocations.get(activity.toolCallId) : undefined
                if (call) {
                    groupInvocations.set(activity.toolCallId!, call)
                }
            }
            if (sameInvocations(old?.groupInvocations, groupInvocations)) {
                groupInvocations = old!.groupInvocations
            }
        }
        const row: ThreadViewRow = {
            item,
            isLast: index === displayItems.length - 1,
            turnId: revealGroups.get(item.id),
            invocation:
                item.type !== 'activity_group' && item.toolCallId ? toolInvocations.get(item.toolCallId) : undefined,
            groupInvocations,
            trailer: trailers?.get(item.id),
        }
        return old &&
            old.item === row.item &&
            old.isLast === row.isLast &&
            old.turnId === row.turnId &&
            old.invocation === row.invocation &&
            old.groupInvocations === row.groupInvocations &&
            old.trailer === row.trailer
            ? old
            : row
    })
}

interface RowShellProps {
    rowClassName?: string
    turnHoverStore: TurnHoverStore
}

const ActivityGroupRow = memo(function ActivityGroupRow({
    group,
    rowClassName,
    turnHoverStore,
    turnId,
    toolInvocations,
    active,
    waitingForInput,
    cancelled,
    turnComplete,
    turnCancelled,
}: RowShellProps & {
    group: ThreadActivityGroupItem
    turnId: string | undefined
    toolInvocations: Map<string, ToolInvocation>
    active: boolean
    waitingForInput: boolean
    cancelled: boolean
    turnComplete: boolean
    turnCancelled: boolean
}): JSX.Element {
    const renderGroupItem = useCallback(
        (activity: ThreadItem): JSX.Element => (
            <ThreadRow
                item={activity}
                isLast={false}
                isThinking={false}
                invocation={activity.toolCallId ? toolInvocations.get(activity.toolCallId) : undefined}
                turnComplete={turnComplete}
                turnCancelled={turnCancelled}
            />
        ),
        [toolInvocations, turnComplete, turnCancelled]
    )
    return (
        <VirtualizedThread.Row className={rowClassName}>
            <TurnReveal store={turnHoverStore} turnId={turnId}>
                <ThreadActivityGroup
                    group={group}
                    toolInvocations={toolInvocations}
                    active={active}
                    waitingForInput={waitingForInput}
                    cancelled={cancelled}
                    renderItem={renderGroupItem}
                />
            </TurnReveal>
        </VirtualizedThread.Row>
    )
})

const TurnTrailerRow = memo(function TurnTrailerRow({
    turnId,
    trailer,
    renderTurnTrailer,
    rowClassName,
    turnHoverStore,
}: RowShellProps & {
    turnId: string
    trailer: TurnTrailer | undefined
    renderTurnTrailer: (trailer: TurnTrailer) => JSX.Element | null
}): JSX.Element {
    return (
        <VirtualizedThread.Row className={rowClassName}>
            {trailer ? (
                <TurnReveal store={turnHoverStore} turnId={turnId}>
                    {renderTurnTrailer(trailer)}
                </TurnReveal>
            ) : null}
        </VirtualizedThread.Row>
    )
})

const ItemRow = memo(function ItemRow({
    item,
    rowClassName,
    turnHoverStore,
    turnId,
    ...rowProps
}: RowShellProps & Omit<ThreadRowProps, 'item'> & { item: ThreadItem; turnId: string | undefined }): JSX.Element {
    return (
        <VirtualizedThread.Row className={rowClassName}>
            <TurnReveal store={turnHoverStore} turnId={turnId}>
                <ThreadRow item={item} {...rowProps} />
            </TurnReveal>
        </VirtualizedThread.Row>
    )
})

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
    extra,
}: {
    showThinking: boolean
    thinkingPhase: 'thinking' | 'provisioning'
    pullRequestUrl?: string
    prBranch?: string
    showContextUsage?: boolean
    showConnectionStatus?: boolean
    extra?: ReactNode
}): JSX.Element {
    // `runConnectionState` is self-subscribed here (like `currentProgress`) so the frequently-updating
    // reconnect attempt counter stays isolated to this leaf and never destabilizes `ThreadView`'s footer.
    const { currentProgress, runConnectionState } = useValues(runStreamLogic)
    const { retryConnection } = useActions(runStreamLogic)
    // `gap-1.5` matches the thread's inter-row gap (`VirtualizedThread`'s `gap` default) so stacked footer
    // items keep the same vertical rhythm as the thread.
    return (
        <div className="flex flex-col gap-1.5">
            {showConnectionStatus && runConnectionState && (
                <RunAlertActivity {...runConnectionState} onRetry={retryConnection} />
            )}
            {showThinking && (
                <ThinkingIndicator
                    progress={thinkingPhase === 'provisioning' ? null : currentProgress}
                    phase={thinkingPhase}
                />
            )}
            {pullRequestUrl && <PullRequestCard prUrl={pullRequestUrl} branch={prBranch} />}
            {showContextUsage && <ContextUsageChip />}
            {extra}
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
