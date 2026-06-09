import { JSX, useState } from 'react'

import { CodeToolKind } from '../acp-types'
import { compactHomePath } from '../lib/path'
import { Icon, ICONS } from '../primitives/icons'
import {
    compactInput,
    ExpandableIcon,
    ExpandedContentBox,
    formatInput,
    getContentText,
    getFilename,
    StatusIndicators,
    stripCodeFences,
    ToolTitle,
    ToolViewProps,
    useToolCallStatus,
} from '../primitives/toolCallUtils'

const kindIcons: Record<CodeToolKind, Icon> = {
    read: ICONS.FileText,
    edit: ICONS.PencilSimple,
    delete: ICONS.Trash,
    move: ICONS.ArrowsLeftRight,
    search: ICONS.MagnifyingGlass,
    execute: ICONS.Terminal,
    think: ICONS.Brain,
    fetch: ICONS.Globe,
    switch_mode: ICONS.ArrowsClockwise,
    question: ICONS.ChatCircle,
    other: ICONS.Wrench,
}

const toolNameIcons: Record<string, Icon> = {
    ToolSearch: ICONS.MagnifyingGlass,
    Skill: ICONS.Command,
}

// Tools that render a friendly "<prefix> `<input>` <suffix>" line instead of
// the raw JSON input preview. `inputKey` is the rawInput field to highlight.
const toolNameDisplays: Record<string, { prefix: string; suffix: string; inputKey: string }> = {
    Skill: { prefix: 'Reading', suffix: 'skill', inputKey: 'skill' },
    ToolSearch: { prefix: 'Searching', suffix: 'tools', inputKey: 'query' },
}

interface ToolCallViewProps extends ToolViewProps {
    agentToolName?: string
}

export function ToolCallView({
    toolCall,
    turnCancelled,
    turnComplete,
    agentToolName,
    expanded = false,
}: ToolCallViewProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(expanded)
    const { title, kind, status, locations, content, rawInput } = toolCall
    const { isLoading, isFailed, wasCancelled, isComplete } = useToolCallStatus(status, turnCancelled, turnComplete)
    const KindIcon = (agentToolName && toolNameIcons[agentToolName]) || (kind && kindIcons[kind]) || ICONS.Wrench

    const filePath = kind === 'read' && locations?.[0]?.path
    const toolDisplay = agentToolName ? toolNameDisplays[agentToolName] : undefined
    const highlightValue =
        toolDisplay && rawInput && typeof rawInput === 'object'
            ? (rawInput as Record<string, unknown>)[toolDisplay.inputKey]
            : undefined
    const specialDisplay =
        toolDisplay && typeof highlightValue === 'string' ? { ...toolDisplay, value: highlightValue } : undefined

    const displayText = specialDisplay
        ? specialDisplay.prefix
        : filePath
          ? `Read ${getFilename(filePath)}`
          : title
            ? compactHomePath(title)
            : undefined

    const inputPreview = specialDisplay?.value ?? compactInput(rawInput)
    const fullInput = formatInput(rawInput)

    const output = stripCodeFences(getContentText(content) ?? '')
    const hasOutput = output.trim().length > 0
    const isExpandable = !!fullInput || hasOutput

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
                        icon={KindIcon}
                        isLoading={isLoading}
                        isExpandable={isExpandable}
                        isExpanded={isExpanded}
                    />
                </div>
                <div className="flex min-w-0 flex-wrap items-center gap-1">
                    <ToolTitle>{displayText}</ToolTitle>
                    {inputPreview && (
                        <ToolTitle>
                            <span className="font-mono text-accent">{inputPreview}</span>
                        </ToolTitle>
                    )}
                    {specialDisplay && <ToolTitle>{specialDisplay.suffix}</ToolTitle>}
                    <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
                </div>
            </div>

            {isExpanded && (
                <>
                    {fullInput && <ExpandedContentBox>{fullInput}</ExpandedContentBox>}
                    {isComplete && hasOutput && <ExpandedContentBox>{output}</ExpandedContentBox>}
                </>
            )}
        </div>
    )
}
