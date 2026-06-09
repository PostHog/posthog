import { JSX, useState } from 'react'

import { IconDocument } from '@posthog/icons'

import { CodePreview } from '../primitives/CodePreview'
import { FileMentionChip } from '../primitives/FileMentionChip'
import {
    ExpandableIcon,
    getContentImage,
    getReadToolContent,
    StatusIndicators,
    ToolTitle,
    ToolViewProps,
    useToolCallStatus,
} from '../primitives/toolCallUtils'

/**
 * Read-only renderer for `read` tool calls. Shows the file (or image) that was
 * read as a one-line title with the file mention chip; clicking expands an
 * inline code listing (or an image preview) via `CodePreview`.
 */
export function ReadToolView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const { status, locations, content } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const filePath = locations?.[0]?.path ?? ''
    const startLine = locations?.[0]?.line ?? 0
    const imageContent = getContentImage(content)
    const fileContent = imageContent ? undefined : getReadToolContent(content)
    const lineCount = fileContent ? fileContent.split('\n').length : null
    const isExpandable = !!fileContent || !!imageContent
    const firstLineNumber = startLine + 1

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
                    icon={IconDocument}
                    isLoading={isLoading}
                    isExpandable={isExpandable}
                    isExpanded={isExpanded}
                />
                <ToolTitle className="shrink-0 whitespace-nowrap">
                    {imageContent ? 'Read image in' : `Read${lineCount !== null ? ` ${lineCount} lines in` : ''}`}
                </ToolTitle>
                {filePath && <FileMentionChip path={filePath} />}
                <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
            </div>

            {isExpanded && imageContent && (
                <div className="mt-2 ml-5">
                    <div className="max-w-4xl overflow-hidden rounded-lg border border-border bg-surface-secondary p-2">
                        <img
                            src={`data:${imageContent.mimeType};base64,${imageContent.base64}`}
                            alt={filePath || 'Read tool image preview'}
                            className="max-h-96 max-w-full object-contain"
                        />
                    </div>
                </div>
            )}

            {isExpanded && fileContent && (
                <div className="mt-2 ml-5">
                    <div className="max-w-4xl overflow-hidden rounded-lg border border-border">
                        <CodePreview content={fileContent} filePath={filePath} firstLineNumber={firstLineNumber} />
                    </div>
                </div>
            )}
        </div>
    )
}
