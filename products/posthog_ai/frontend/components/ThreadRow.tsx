import { memo } from 'react'

import { IconCopy, IconWrench } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { TaskExecutionStatus as ExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import { DebugMessage } from '../messages/DebugMessage'
import { MarkdownMessage } from '../messages/MarkdownMessage'
import { MessageTemplate } from '../messages/MessageTemplate'
import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import type { ProgressStep, ThreadItem, ToolInvocation } from '../types/streamTypes'
import { toolInvocationToMessage } from '../utils/toolCallMessage'
import { userMessageDisplayText } from '../utils/userMessageDisplay'
import { Activity } from './ActivityPrimitives'
import { QuillAssistantMessage, QuillHumanMessage } from './quill/QuillMessages'
import { QuillSeparatorRow } from './quill/QuillSeparatorRow'
import { useQuillThread } from './quill/quillThreadContext'
import { RunErrorRow } from './RunErrorRow'
import { ThreadAttachments } from './ThreadAttachments'
import { CompactBoundaryItem, ConversationClearedItem, StatusItem, TaskNotificationItem } from './ThreadItems'
import { ToolCallCard } from './tool/ToolCallCard'

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
        <Activity
            id={item.id}
            title={headline}
            substeps={substeps}
            status={state}
            icon={<IconWrench />}
            showCompletionIcon={true}
            autoExpand={false}
        />
    )
}

export interface ThreadRowProps {
    item: ThreadItem
    /** Last item in the thread — drives reasoning collapse alongside `isThinking`. */
    isLast: boolean
    isThinking: boolean
    invocation?: ToolInvocation
    turnComplete: boolean
    turnCancelled: boolean
    /** The current run reached a terminal status; only then is the last error the run's ending. */
    runEnded?: boolean
}

/** Hidden at rest so a long thread does not repeat a row under every message. */
function HumanMessageFooter({ startedAt, text }: { startedAt?: number; text?: string }): JSX.Element {
    return (
        <div className="flex items-center gap-1 mt-1.5 mr-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            {startedAt !== undefined && (
                // A fresh dayjs object every render would defeat TZLabel's memo; a string compares by value.
                <TZLabel time={new Date(startedAt).toISOString()} className="text-xs text-muted" />
            )}
            {text && (
                <LemonButton
                    icon={<IconCopy />}
                    type="tertiary"
                    size="xsmall"
                    tooltip="Copy message"
                    data-attr="posthog-ai-human-message-copy"
                    onClick={() => void copyToClipboard(text)}
                />
            )}
        </div>
    )
}

/**
 * Renders a single sandbox thread item by type. Memoized and keyed by stable `item.id` so a re-projected
 * `threadItems` array only re-renders rows whose data actually changed.
 */
export const ThreadRow = memo(function ThreadRow({
    item,
    isLast,
    isThinking,
    invocation,
    turnComplete,
    turnCancelled,
    runEnded = true,
}: ThreadRowProps): JSX.Element | null {
    const quill = useQuillThread()
    if (item.type === 'human_message') {
        if (quill) {
            return <QuillHumanMessage item={item} />
        }
        const text = userMessageDisplayText(item.text ?? '')
        return (
            <MessageTemplate
                type="human"
                className="group"
                action={<HumanMessageFooter startedAt={item.startedAt} text={text} />}
            >
                <MarkdownMessage content={text || '*No text.*'} id={item.id} />
                {item.attachments && <ThreadAttachments attachments={item.attachments} />}
            </MessageTemplate>
        )
    }
    if (item.type === 'assistant_message') {
        if (quill) {
            return <QuillAssistantMessage item={item} />
        }
        return (
            <MessageTemplate type="ai" wrapperClassName="max-w-4/5">
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
        const message = toolInvocationToMessage(invocation)
        if (!message) {
            return null
        }
        return <ToolCallCard message={message} turnComplete={turnComplete} turnCancelled={turnCancelled} />
    }
    if (item.type === 'error') {
        return <RunErrorRow item={item} isLast={isLast && runEnded} />
    }
    if (quill && (item.type === 'status' || item.type === 'compact_boundary' || item.type === 'conversation_cleared')) {
        return <QuillSeparatorRow item={item} live={isLast && isThinking} />
    }
    if (item.type === 'status') {
        return <StatusItem item={item} />
    }
    if (item.type === 'compact_boundary') {
        return <CompactBoundaryItem item={item} />
    }
    if (item.type === 'conversation_cleared') {
        return <ConversationClearedItem item={item} />
    }
    if (item.type === 'task_notification') {
        return <TaskNotificationItem item={item} />
    }
    if (item.type === 'progress') {
        return <ProgressItem item={item} />
    }
    if (item.type === 'debug') {
        return (
            <DebugMessage
                text={item.text ?? ''}
                level={item.debugLevel ?? 'info'}
                copyable={item.debugLevel === 'context'}
            />
        )
    }
    return null
})
