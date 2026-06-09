import { JSX } from 'react'

import type { ToolCall } from './acp-types'
import type { ConversationItem, TurnContext } from './buildConversationItems'
import type { ToolViewProps } from './primitives/toolCallUtils'
import { DeleteToolView } from './tools/DeleteToolView'
import { EditToolView } from './tools/EditToolView'
import { ExecuteToolView } from './tools/ExecuteToolView'
import { FetchToolView } from './tools/FetchToolView'
import { McpToolBlock } from './tools/McpToolBlock'
import { MoveToolView } from './tools/MoveToolView'
import { PlanApprovalView } from './tools/PlanApprovalView'
import { QuestionToolView } from './tools/QuestionToolView'
import { ReadToolView } from './tools/ReadToolView'
import { SearchToolView } from './tools/SearchToolView'
import { SubagentToolView } from './tools/SubagentToolView'
import { ThinkToolView } from './tools/ThinkToolView'
import { ToolCallView } from './tools/ToolCallView'

interface ToolCallBlockProps extends ToolViewProps {
    childItems?: ConversationItem[]
    childItemsMap?: Map<string, ConversationItem[]>
}

/**
 * Read-only port of PostHog Code's `ToolCallBlock`. Resolves the concrete tool
 * renderer from the Claude-supplied tool name (`_meta.claudeCode.toolName`) and
 * the ACP tool kind, then renders it indented under the turn.
 */
export function ToolCallBlock({
    toolCall,
    turnCancelled,
    turnComplete,
    childItems,
    childItemsMap,
}: ToolCallBlockProps): JSX.Element | null {
    const meta = toolCall._meta as { claudeCode?: { toolName?: string } } | undefined
    const toolName = meta?.claudeCode?.toolName

    if (toolName === 'EnterPlanMode') {
        return null
    }

    const props: ToolViewProps = { toolCall, turnCancelled, turnComplete }

    if ((toolName === 'Task' || toolName === 'Agent') && childItems && childItems.length > 0) {
        const turnContext: TurnContext = {
            toolCalls: buildChildToolCallsMap(childItems),
            childItems: childItemsMap ?? new Map(),
            turnCancelled: turnCancelled ?? false,
            turnComplete: turnComplete ?? false,
        }
        return (
            <div className="pl-3">
                <SubagentToolView {...props} childItems={childItems} turnContext={turnContext} />
            </div>
        )
    }

    if (toolName?.startsWith('mcp__')) {
        return (
            <div className="pl-3">
                <McpToolBlock {...props} mcpToolName={toolName} />
            </div>
        )
    }

    const content = ((): JSX.Element | null => {
        switch (toolCall.kind) {
            case 'switch_mode':
                return <PlanApprovalView {...props} />
            case 'execute':
                return <ExecuteToolView {...props} />
            case 'read':
                return <ReadToolView {...props} />
            case 'edit':
                return <EditToolView {...props} />
            case 'delete':
                return <DeleteToolView {...props} />
            case 'move':
                return <MoveToolView {...props} />
            case 'search':
                return <SearchToolView {...props} />
            case 'think':
                return <ThinkToolView {...props} />
            case 'fetch':
                return <FetchToolView {...props} />
            case 'question':
                return <QuestionToolView {...props} />
            default:
                return <ToolCallView {...props} agentToolName={toolName} />
        }
    })()

    return <div className="pl-3">{content}</div>
}

function buildChildToolCallsMap(childItems: ConversationItem[]): Map<string, ToolCall> {
    const map = new Map<string, ToolCall>()
    for (const item of childItems) {
        if (item.type === 'session_update' && item.update.sessionUpdate === 'tool_call') {
            const tc = item.update as unknown as ToolCall
            if (tc.toolCallId) {
                map.set(tc.toolCallId, tc)
            }
        }
    }
    return map
}
