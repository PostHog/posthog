import { JSX, useState } from 'react'

import { ICONS } from '../primitives/icons'
import {
    ContentPre,
    ExpandableIcon,
    findResourceLink,
    getContentText,
    StatusIndicators,
    ToolTitle,
    type ToolViewProps,
    truncateText,
    useToolCallStatus,
} from '../primitives/toolCallUtils'

const MAX_URL_LENGTH = 60

export function FetchToolView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const { status, content, title } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const resourceLink = findResourceLink(content)
    const fetchedContent = getContentText(content) ?? ''
    const hasContent = fetchedContent.trim().length > 0

    const url = resourceLink?.uri ?? ''
    const isExpandable = hasContent || url.length > MAX_URL_LENGTH

    const handleClick = (): void => {
        if (isExpandable) {
            setIsExpanded(!isExpanded)
        }
    }

    return (
        <div>
            <div
                className={`group flex min-w-0 items-center gap-2 py-0.5 ${isExpandable ? 'cursor-pointer' : ''}`}
                onClick={handleClick}
            >
                <ExpandableIcon
                    icon={ICONS.Globe}
                    isLoading={isLoading}
                    isExpandable={isExpandable}
                    isExpanded={isExpanded}
                />
                <ToolTitle>{title || 'Fetch'}</ToolTitle>
                {url && (
                    <ToolTitle>
                        <span className="font-mono text-accent">{truncateText(url, MAX_URL_LENGTH)}</span>
                    </ToolTitle>
                )}
                <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
            </div>

            {isExpanded && (
                <div className="max-w-4xl overflow-hidden rounded-lg border border-border">
                    {url.length > MAX_URL_LENGTH && (
                        <div className={hasContent ? 'border-b border-border px-3 py-2' : 'px-3 py-2'}>
                            <span className="break-all text-[13px] text-muted">{url}</span>
                        </div>
                    )}
                    {hasContent && <ContentPre>{fetchedContent}</ContentPre>}
                </div>
            )}
        </div>
    )
}
