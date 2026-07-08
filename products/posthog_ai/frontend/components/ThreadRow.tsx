import { memo } from 'react'

import { IconWrench } from '@posthog/icons'

import { TaskExecutionStatus as ExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { runStreamLogic } from '../logics/runStreamLogic'
import { DebugMessage } from '../messages/DebugMessage'
import { MarkdownMessage } from '../messages/MarkdownMessage'
import { MessageTemplate } from '../messages/MessageTemplate'
import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import type { ProgressStep, ThreadItem } from '../types/streamTypes'
import { RunActivity } from './RunActivity'
import { RunAlertActivity } from './RunAlertActivity'
import { CompactBoundaryItem, StatusItem, TaskNotificationItem } from './ThreadItems'
import { ToolCallCard } from './tool/ToolCallCard'
import { resolveToolCall } from './tool/toolResolver'

type ToolInvocations = typeof runStreamLogic.values.toolInvocations

/** Maps a raw merged `ToolInvocation` into the flat `ToolCallMessage` the registry renderers read. */
function toolInvocationToMessage(invocation: ReturnType<ToolInvocations['get']>): ToolCallMessage | null {
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

function progressStepText(step: ProgressStep): string {
    return step.detail ? `${step.label}\n\n${step.detail}` : step.label
}

function resolveProgressState(steps: ProgressStep[]): ExecutionStatus {
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

function resolveProgressHeadline(steps: ProgressStep[]): string {
    const active = steps.find((step) => step.status === 'in_progress')
    if (active) {
        return active.label
    }
    return steps.at(-1)?.label ?? 'Working'
}

function ProgressItem({ item }: { item: ThreadItem }): JSX.Element | null {
    const steps = item.progressSteps ?? []
    if (!steps.length) {
        return null
    }

    const headline = resolveProgressHeadline(steps)
    const substeps = steps.length > 1 ? steps.map(progressStepText) : []
    const state = resolveProgressState(steps)

    return (
        <RunActivity
            id={item.id}
            content={headline}
            substeps={substeps}
            state={state}
            icon={<IconWrench />}
            showCompletionIcon={true}
        />
    )
}

export interface ThreadRowProps {
    item: ThreadItem
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
export const ThreadRow = memo(function ThreadRow({
    item,
    isLast,
    isThinking,
    toolInvocations,
    turnComplete,
    turnCancelled,
}: ThreadRowProps): JSX.Element | null {
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
        return <ToolCallCard message={message} turnComplete={turnComplete} turnCancelled={turnCancelled} />
    }
    if (item.type === 'error') {
        return (
            <RunAlertActivity
                id={item.id}
                kind={item.variant === 'crash' ? 'agent_crash' : 'agent_error'}
                message={item.errorMessage}
            />
        )
    }
    if (item.type === 'status') {
        return <StatusItem item={item} />
    }
    if (item.type === 'compact_boundary') {
        return <CompactBoundaryItem item={item} />
    }
    if (item.type === 'task_notification') {
        return <TaskNotificationItem item={item} />
    }
    if (item.type === 'progress') {
        return <ProgressItem item={item} />
    }
    if (item.type === 'debug') {
        return <DebugMessage text={item.text ?? ''} level={item.debugLevel ?? 'info'} />
    }
    return null
})
