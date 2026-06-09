import { JSX, memo } from 'react'

import type { ToolCall } from './acp-types'
import type { ConversationItem, RenderItem } from './buildConversationItems'
import { AgentMessage } from './messages/AgentMessage'
import { CompactBoundaryView } from './messages/CompactBoundaryView'
import { ConsoleMessage } from './messages/ConsoleMessage'
import { ErrorNotificationView } from './messages/ErrorNotificationView'
import { ProgressGroupView } from './messages/ProgressGroupView'
import { StatusNotificationView } from './messages/StatusNotificationView'
import { TaskNotificationView } from './messages/TaskNotificationView'
import { ThoughtView } from './messages/ThoughtView'
import { ToolCallBlock } from './ToolCallBlock'

export type { RenderItem }

interface SessionUpdateViewProps {
    item: RenderItem
    toolCalls?: Map<string, ToolCall>
    childItems?: Map<string, ConversationItem[]>
    turnCancelled?: boolean
    turnComplete?: boolean
    thoughtComplete?: boolean
}

function parseConsoleTimestamp(timestamp?: string): number | undefined {
    if (!timestamp) {
        return undefined
    }
    const parsed = new Date(timestamp).getTime()
    return Number.isNaN(parsed) ? undefined : parsed
}

/**
 * Read-only port of PostHog Code's `SessionUpdateView`. Dispatches a single
 * `RenderItem` to its concrete renderer. Synthetic updates (console,
 * compact_boundary, status, error, task_notification, progress_group) are
 * widened onto the ACP `SessionUpdate` union in `buildConversationItems`.
 */
export const SessionUpdateView = memo(function SessionUpdateView({
    item,
    toolCalls,
    childItems,
    turnCancelled,
    turnComplete,
    thoughtComplete,
}: SessionUpdateViewProps): JSX.Element | null {
    switch (item.sessionUpdate) {
        case 'user_message_chunk':
            return null
        case 'agent_message_chunk':
            return item.content.type === 'text' ? <AgentMessage content={item.content.text} /> : null
        case 'agent_thought_chunk':
            return item.content.type === 'text' ? (
                <ThoughtView content={item.content.text} isLoading={!thoughtComplete} />
            ) : null
        case 'tool_call':
            return (
                <ToolCallBlock
                    toolCall={toolCalls?.get(item.toolCallId) ?? item}
                    turnCancelled={turnCancelled}
                    turnComplete={turnComplete}
                    childItems={childItems?.get(item.toolCallId)}
                    childItemsMap={childItems}
                />
            )
        case 'tool_call_update':
            return null
        case 'plan':
            return null
        case 'available_commands_update':
            return null
        case 'config_option_update':
            return null
        case 'console':
            return (
                <ConsoleMessage
                    level={item.level as 'info' | 'debug' | 'warn' | 'error'}
                    message={item.message}
                    timestamp={parseConsoleTimestamp(item.timestamp)}
                />
            )
        case 'compact_boundary':
            return (
                <CompactBoundaryView trigger={item.trigger} preTokens={item.preTokens} contextSize={item.contextSize} />
            )
        case 'status':
            return <StatusNotificationView status={item.status} isComplete={item.isComplete} />
        case 'error':
            return <ErrorNotificationView errorType={item.errorType} message={item.message} />
        case 'task_notification':
            return <TaskNotificationView status={item.status} summary={item.summary} />
        case 'progress_group':
            return <ProgressGroupView steps={item.steps} isActive={item.isActive} turnComplete={turnComplete} />
        default:
            return null
    }
})
