import { JSX, useState } from 'react'

import { compactHomePath } from '../lib/path'
import { stripAnsi } from '../strip-ansi'
import { ICONS } from '../primitives/icons'
import {
    ExpandableIcon,
    ExpandedContentBox,
    getContentText,
    StatusIndicators,
    stripCodeFences,
    ToolTitle,
    type ToolViewProps,
    truncateText,
    useToolCallStatus,
} from '../primitives/toolCallUtils'

const MAX_COMMAND_LENGTH = 120

interface ExecuteRawInput {
    command?: string
    description?: string
}

export function ExecuteToolView({ toolCall, turnCancelled, turnComplete, expanded = false }: ToolViewProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(expanded)
    const { status, rawInput, content, title } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const executeInput = rawInput as ExecuteRawInput | undefined
    const command = executeInput?.command ?? ''
    const description = executeInput?.description ?? (command ? undefined : title)

    const output = stripAnsi(stripCodeFences(getContentText(content) ?? ''))
    const hasOutput = output.trim().length > 0
    const isExpandable = hasOutput

    const handleClick = (): void => {
        if (isExpandable) {
            setIsExpanded(!isExpanded)
        }
    }

    return (
        <div className="py-0.5">
            <div
                className={`group flex min-w-0 gap-2 ${isExpandable ? 'cursor-pointer' : ''}`}
                onClick={handleClick}
            >
                <div className="shrink-0 pt-px">
                    <ExpandableIcon
                        icon={ICONS.Terminal}
                        isLoading={isLoading}
                        isExpandable={isExpandable}
                        isExpanded={isExpanded}
                    />
                </div>
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                    {description && <ToolTitle>{description}</ToolTitle>}
                    {command && (
                        <ToolTitle className="min-w-0 truncate">
                            <span className="font-mono text-accent" title={command}>
                                {truncateText(compactHomePath(command), MAX_COMMAND_LENGTH)}
                            </span>
                        </ToolTitle>
                    )}
                    <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
                </div>
            </div>

            {isExpanded && hasOutput && <ExpandedContentBox>{output}</ExpandedContentBox>}
        </div>
    )
}
