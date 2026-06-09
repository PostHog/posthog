import { JSX, useState } from 'react'

import { ICONS } from '../primitives/icons'
import {
    ExpandableIcon,
    ExpandedContentBox,
    getContentText,
    StatusIndicators,
    ToolTitle,
    type ToolViewProps,
    useToolCallStatus,
} from '../primitives/toolCallUtils'
import { ToolRow } from './ToolRow'

export function SearchToolView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const { status, content, title } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const searchResults = getContentText(content) ?? ''
    const hasResults = searchResults.trim().length > 0
    const resultLines = hasResults ? searchResults.split('\n').filter((line) => line.trim().length > 0) : []
    const resultCount = resultLines.length

    if (!hasResults) {
        return (
            <ToolRow icon={ICONS.MagnifyingGlass} isLoading={isLoading} isFailed={isFailed} wasCancelled={wasCancelled}>
                {title || 'Search'}
            </ToolRow>
        )
    }

    const handleClick = (): void => {
        setIsExpanded(!isExpanded)
    }

    return (
        <div>
            <div className="group flex min-w-0 cursor-pointer items-center gap-2 py-0.5" onClick={handleClick}>
                <ExpandableIcon
                    icon={ICONS.MagnifyingGlass}
                    isLoading={isLoading}
                    isExpandable
                    isExpanded={isExpanded}
                />
                <ToolTitle className="min-w-0 truncate">
                    <span className="font-mono">{title || 'Search'}</span>
                </ToolTitle>
                <ToolTitle className="shrink-0 whitespace-nowrap">
                    {resultCount} {resultCount === 1 ? 'result' : 'results'}
                </ToolTitle>
                <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
            </div>

            {isExpanded && <ExpandedContentBox>{searchResults}</ExpandedContentBox>}
        </div>
    )
}
