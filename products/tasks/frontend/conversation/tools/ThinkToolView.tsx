import { JSX, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { IconBrain, IconCollapse, IconExpand } from '../primitives/icons'
import { getContentText, LoadingIcon, type ToolViewProps, useToolCallStatus } from '../primitives/toolCallUtils'
import { ToolRow } from './ToolRow'

const COLLAPSED_LINE_COUNT = 5

export function ThinkToolView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const { status, content, title } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const thinkingContent = getContentText(content) ?? ''
    const hasContent = thinkingContent.trim().length > 0
    const contentLines = thinkingContent.split('\n')
    const isCollapsible = contentLines.length > COLLAPSED_LINE_COUNT
    const hiddenLineCount = contentLines.length - COLLAPSED_LINE_COUNT
    const displayedContent = isExpanded ? thinkingContent : contentLines.slice(0, COLLAPSED_LINE_COUNT).join('\n')

    if (!hasContent) {
        return (
            <ToolRow icon={IconBrain} isLoading={isLoading} isFailed={isFailed} wasCancelled={wasCancelled}>
                {title || 'Thinking'}
            </ToolRow>
        )
    }

    return (
        <div className="my-2 max-w-4xl overflow-hidden rounded-lg border border-border">
            <div className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-2">
                    <LoadingIcon icon={IconBrain} isLoading={isLoading} className="text-muted" />
                    <span className="text-[13px] text-muted">{title || 'Thinking'}</span>
                </div>
                {isCollapsible && (
                    <LemonButton
                        size="small"
                        icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                        onClick={() => setIsExpanded(!isExpanded)}
                        tooltip={isExpanded ? 'Collapse' : 'Expand'}
                    />
                )}
            </div>

            <div className="border-t border-border px-3 py-2">
                <pre className="m-0 whitespace-pre-wrap break-all font-mono text-[13px] text-muted">
                    {displayedContent}
                </pre>
                {isCollapsible && !isExpanded && (
                    <button
                        type="button"
                        onClick={() => setIsExpanded(true)}
                        className="mt-1 flex cursor-pointer items-center gap-1 border-none bg-transparent p-0 text-muted hover:text-default"
                    >
                        <span className="text-[13px]">+{hiddenLineCount} more lines</span>
                    </button>
                )}
            </div>
        </div>
    )
}
