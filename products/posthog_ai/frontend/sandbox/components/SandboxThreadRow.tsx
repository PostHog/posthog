import { memo } from 'react'

import { IconWrench } from '@posthog/icons'

import { TaskExecutionStatus as ExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import type { SandboxToolCallMessage } from 'products/posthog_ai/frontend/sandbox/types/sandboxToolTypes'

import { MarkdownMessage } from '../MarkdownMessage'
import { AssistantFailureMessage } from '../messages/AssistantFailureMessage'
import { MessageTemplate } from '../messages/MessageTemplate'
import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import { SandboxDebugMessage } from '../messages/SandboxDebugMessage'
import { SandboxActivity } from '../SandboxActivity'
import { sandboxStreamLogic } from '../sandboxStreamLogic'
import { SandboxCompactBoundaryItem, SandboxStatusItem, SandboxTaskNotificationItem } from '../SandboxThreadItems'
import { resolveToolCall } from '../sandboxToolResolver'
import type { SandboxProgressStep, ThreadItem as SandboxThreadItem } from '../types/sandboxStreamTypes'
import { SandboxToolCall } from './tool/SandboxToolCall'

type ToolInvocations = typeof sandboxStreamLogic.values.toolInvocations

/** Maps a raw merged `ToolInvocation` into the flat `SandboxToolCallMessage` the registry renderers read. */
function toolInvocationToMessage(invocation: ReturnType<ToolInvocations['get']>): SandboxToolCallMessage | null {
    if (!invocation) {
        return null
    }
    const resolved = resolveToolCall(invocation)
    return {
        id: invocation.toolCallId,
        resolvedKey: resolved.resolvedKey,
        rawServerName: invocation.rawServerName,
        rawToolName: invocation.rawToolName,
        innerToolName: resolved.innerToolName,
        claudeToolName: resolved.claudeToolName,
        rawInput: invocation.input,
        innerInput: resolved.innerInput,
        rawOutput: invocation.output,
        content: invocation.contentBlocks,
        status: invocation.status,
        title: invocation.title,
        kind: invocation.kind,
        locations: invocation.locations,
        error: invocation.error,
    }
}

function progressStepText(step: SandboxProgressStep): string {
    return step.detail ? `${step.label}\n\n${step.detail}` : step.label
}

function resolveSandboxProgressState(steps: SandboxProgressStep[]): ExecutionStatus {
    if (steps.some((step) => step.status === 'failed')) {
        return ExecutionStatus.Failed
    }
    if (steps.some((step) => step.status === 'in_progress')) {
        return ExecutionStatus.InProgress
    }
    if (steps.length > 0 && steps.every((step) => step.status === 'pending')) {
        return ExecutionStatus.Pending
    }
    return ExecutionStatus.Completed
}

function resolveSandboxProgressHeadline(steps: SandboxProgressStep[]): string {
    const active = steps.find((step) => step.status === 'in_progress')
    if (active) {
        return active.label
    }
    return steps.at(-1)?.label ?? 'Working'
}

function SandboxProgressItem({ item }: { item: SandboxThreadItem }): JSX.Element | null {
    const steps = item.progressSteps ?? []
    if (!steps.length) {
        return null
    }

    const headline = resolveSandboxProgressHeadline(steps)
    const substeps = steps.length > 1 ? steps.map(progressStepText) : []
    const state = resolveSandboxProgressState(steps)

    return (
        <SandboxActivity
            id={item.id}
            content={headline}
            substeps={substeps}
            state={state}
            icon={<IconWrench />}
            showCompletionIcon={true}
        />
    )
}

export interface SandboxThreadRowProps {
    item: SandboxThreadItem
    /** Last item in the thread — drives reasoning collapse alongside `isThinking`. */
    isLast: boolean
    isThinking: boolean
    toolInvocations: ToolInvocations
    turnComplete: boolean
    turnCancelled: boolean
}

/**
 * Renders a single sandbox thread item by type. Memoized and keyed by stable `item.id` so a re-projected
 * `threadItems` array only re-renders rows whose data actually changed.
 */
export const SandboxThreadRow = memo(function SandboxThreadRow({
    item,
    isLast,
    isThinking,
    toolInvocations,
    turnComplete,
    turnCancelled,
}: SandboxThreadRowProps): JSX.Element | null {
    if (item.type === 'human_message') {
        return (
            <MessageTemplate type="human">
                <MarkdownMessage content={item.text || '*No text.*'} id={item.id} />
            </MessageTemplate>
        )
    }
    if (item.type === 'assistant_message') {
        return (
            <MessageTemplate type="ai">
                <MarkdownMessage content={item.text ?? ''} id={item.id} />
            </MessageTemplate>
        )
    }
    if (item.type === 'assistant_thought') {
        // Empty chunks prime the stream before any reasoning text arrives — skip them so a contentless
        // "Thought" never shows; the bottom indicator covers that gap.
        if (!item.text?.trim()) {
            return null
        }
        // Collapse to "Thought" once a later block starts or the run stops thinking — mirrors the LangGraph
        // thread's reasoning-complete rule.
        const completed = !isLast || !isThinking
        return <ReasoningAnswer content={item.text} id={item.id} completed={completed} showCompletionIcon={false} />
    }
    if (item.type === 'tool_invocation' && item.toolCallId) {
        const message = toolInvocationToMessage(toolInvocations.get(item.toolCallId))
        if (!message) {
            return null
        }
        return <SandboxToolCall message={message} turnComplete={turnComplete} turnCancelled={turnCancelled} />
    }
    if (item.type === 'error') {
        return <AssistantFailureMessage id={item.id} content={item.errorMessage} />
    }
    if (item.type === 'status') {
        return <SandboxStatusItem item={item} />
    }
    if (item.type === 'compact_boundary') {
        return <SandboxCompactBoundaryItem item={item} />
    }
    if (item.type === 'task_notification') {
        return <SandboxTaskNotificationItem item={item} />
    }
    if (item.type === 'progress') {
        return <SandboxProgressItem item={item} />
    }
    if (item.type === 'debug') {
        return <SandboxDebugMessage id={item.id} text={item.text ?? ''} level={item.debugLevel ?? 'info'} />
    }
    return null
})
