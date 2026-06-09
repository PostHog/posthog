import { JSX, useState } from 'react'

import type { ConversationItem, TurnContext } from '../buildConversationItems'
import { IconAI, IconCollapse, IconExpand } from '../primitives/icons'
import { LoadingIcon, StatusIndicators, type ToolViewProps, useToolCallStatus } from '../primitives/toolCallUtils'
import { SessionUpdateView } from '../SessionUpdateView'

interface SubagentToolViewProps extends ToolViewProps {
    childItems: ConversationItem[]
    turnContext: TurnContext
}

export function SubagentToolView({
    toolCall,
    turnCancelled,
    turnComplete,
    childItems,
    turnContext,
}: SubagentToolViewProps): JSX.Element {
    const { title } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(toolCall.status, turnCancelled, turnComplete)

    const [isExpanded, setIsExpanded] = useState(false)

    const hasChildren = childItems.length > 0

    return (
        <div className="my-2 max-w-4xl overflow-hidden rounded-lg border border-border bg-bg-light">
            <button
                type="button"
                onClick={() => setIsExpanded(!isExpanded)}
                className="flex w-full cursor-pointer items-center justify-between border-none bg-transparent px-3 py-2"
            >
                <div className="flex items-center gap-2">
                    <LoadingIcon icon={IconAI} isLoading={isLoading} className="text-muted" />
                    <span className="text-[13px] text-muted">{title || 'Subagent'}</span>
                    <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
                </div>
                {hasChildren && (
                    <span className="text-muted">
                        {isExpanded ? (
                            <IconCollapse style={{ fontSize: 12 }} />
                        ) : (
                            <IconExpand style={{ fontSize: 12 }} />
                        )}
                    </span>
                )}
            </button>

            {isExpanded && hasChildren && (
                <div className="space-y-1 border-t border-border px-2 py-2">
                    {childItems.map((child) => {
                        if (child.type !== 'session_update') {
                            return null
                        }
                        return (
                            <SessionUpdateView
                                key={child.id}
                                item={child.update}
                                toolCalls={turnContext.toolCalls}
                                childItems={turnContext.childItems}
                                turnCancelled={turnContext.turnCancelled}
                                turnComplete={turnContext.turnComplete}
                            />
                        )
                    })}
                </div>
            )}
        </div>
    )
}
