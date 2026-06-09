import { JSX, memo, useState } from 'react'

import { ExpandableIcon } from '../primitives/toolCallUtils'
import { IconBrain } from '../primitives/icons'
import { MarkdownMessage } from '../primitives/MarkdownMessage'

interface ThoughtViewProps {
    content: string
    isLoading: boolean
}

const COLLAPSED_LINE_COUNT = 5

/**
 * Collapsible "thinking" block. Renders the agent's reasoning, muted and folded
 * to a few lines by default. While the turn is still streaming (`isLoading`),
 * the leading icon shows a spinner instead of the brain.
 */
export const ThoughtView = memo(function ThoughtView({ content, isLoading }: ThoughtViewProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    const hasContent = content.trim().length > 0
    const contentLines = content.split('\n')
    const isCollapsible = hasContent && contentLines.length > COLLAPSED_LINE_COUNT
    const hiddenLineCount = contentLines.length - COLLAPSED_LINE_COUNT
    const displayedContent = isExpanded ? content : contentLines.slice(0, COLLAPSED_LINE_COUNT).join('\n')

    return (
        <div>
            <button
                type="button"
                onClick={() => hasContent && setIsExpanded((v) => !v)}
                className={`group flex items-center gap-2 border-none bg-transparent p-0 py-0.5 ${
                    hasContent ? 'cursor-pointer' : 'cursor-default'
                }`}
            >
                <ExpandableIcon
                    icon={IconBrain}
                    isLoading={isLoading}
                    isExpandable={hasContent}
                    isExpanded={isExpanded}
                />
                <span className="text-[13px] text-muted">Thinking</span>
            </button>
            {isExpanded && hasContent && (
                <div className="mt-1 ml-5 max-w-4xl overflow-hidden rounded-lg border border-border">
                    <div className="max-h-64 overflow-auto px-3 py-2 text-[13px] text-muted">
                        <MarkdownMessage content={displayedContent} />
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
            )}
        </div>
    )
})
