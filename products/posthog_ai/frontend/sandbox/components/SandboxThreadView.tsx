import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import { SandboxPullRequestCard } from '../SandboxPullRequestCard'
import { SandboxRunContext } from '../SandboxRunContext'
import { sandboxStreamLogic } from '../sandboxStreamLogic'
import type { ThreadItem } from '../types/sandboxStreamTypes'
import { getRandomThinkingMessage } from '../utils/thinkingMessages'
import { SandboxThreadRow } from './SandboxThreadRow'
import { VirtualizedThread } from './VirtualizedThread'

/**
 * Sandbox-runtime thread presenter. Reads `sandboxStreamLogic.values.threadItems` (assistant text,
 * tool-invocation references, run separators, inline errors) from whatever `sandboxStreamLogic`
 * instance is bound above it — a live PostHog AI conversation or a read-only run viewer — and
 * dispatches tool cards through the sandbox tool registry. Conversation-agnostic by design: it knows
 * only the bound stream logic, never langgraph vs sandbox or the conversation.
 *
 * Rows are virtualized through `VirtualizedThread`, which owns scroll and stick-to-bottom; the leading
 * run context and trailing thinking indicator / PR card ride along as the header/footer rows. Pass
 * `virtualized={false}` when an ancestor already owns scroll (the live Max column + auto-scroller) — rows
 * then render in document flow, unchanged from the pre-virtualized layout.
 */
export function SandboxThreadView({ virtualized = true }: { virtualized?: boolean } = {}): JSX.Element {
    // Drive the thinking indicator from real agent progress: show the latest `_posthog/progress`
    // message while the run is active, falling back to the canned rotation.
    const {
        threadItems,
        toolInvocations,
        currentProgress,
        isThinking,
        streamPhase,
        runArtifacts,
        turnComplete,
        currentRunStatus,
    } = useValues(sandboxStreamLogic)
    const turnCancelled = currentRunStatus === 'cancelled'
    const hasActiveProgressItem = threadItems.some(
        (item) => item.type === 'progress' && item.progressSteps?.some((step) => step.status === 'in_progress')
    )

    const header = runArtifacts.branch ? (
        <SandboxRunContext branch={runArtifacts.branch} baseBranch={runArtifacts.baseBranch} repo={runArtifacts.repo} />
    ) : undefined

    const showThinking = streamPhase === 'thinking' && !hasActiveProgressItem
    // Post-turn only: a reconnect refetch can fold in a pr_url mid-run, so gate on !isThinking.
    const pullRequestUrl = !isThinking ? runArtifacts.prUrl : undefined
    const footer =
        showThinking || pullRequestUrl ? (
            <>
                {showThinking && <SandboxThinkingIndicator progress={currentProgress} />}
                {pullRequestUrl && <SandboxPullRequestCard prUrl={pullRequestUrl} branch={runArtifacts.branch} />}
            </>
        ) : undefined

    const renderItem = useCallback(
        (item: ThreadItem, index: number): JSX.Element => (
            <VirtualizedThread.Row>
                <SandboxThreadRow
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
            getItemKey={(item) => item.id}
            header={header}
            footer={footer}
            stickToBottom
            virtualized={virtualized}
        >
            {renderItem}
        </VirtualizedThread.Root>
    )
}

/**
 * Bottom-of-thread "what's it doing right now" line for sandbox conversations. Reflects the latest
 * `_posthog/progress` message when present, otherwise the canned thinking rotation.
 */
function SandboxThinkingIndicator({ progress }: { progress: string | null }): JSX.Element {
    // One roll per mount — re-rolling on every progress transition would visibly swap the verb.
    const fallbackMessage = useMemo(() => getRandomThinkingMessage(), [])
    const message = progress?.trim() ? progress : fallbackMessage
    // Match the LangGraph loader: a bubble-free reasoning line (muted brain icon + muted text),
    // static (no shimmer), via the shared Activity primitive — not a MessageTemplate bubble.
    return <ReasoningAnswer content={message} id="sandbox-thinking" completed={false} showCompletionIcon={false} />
}
