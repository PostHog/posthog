/**
 * Component for rendering different segment types (truncated, gen_expandable, tools_expandable)
 */
import { IconExternal } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { VISIBLE_TOOLS_COUNT } from '../constants'
import { TextSegment } from '../parsing'
import { NestedContentRenderer } from './NestedContentRenderer'
import { TextWithLinks } from './TextWithLinks'

interface SegmentRendererProps {
    segment: TextSegment
    index: number
    traceId?: string
    isExpanded: boolean
    isPopoutOpen: boolean
    onToggleExpand: (index: number) => void
    onTogglePopout: (index: number) => void
    expandedSegments: Set<number | string>
    setExpandedSegments: (segments: Set<number | string>) => void
    popoutSegment: number | string | null
    setPopoutSegment: (index: number | string | null) => void
    activeLineNumber?: number | null
    lineNumberPadding?: number
    onCopyPermalink?: (lineNumber: number) => void
    enableLineActions?: boolean
}

export function SegmentRenderer({
    segment,
    index,
    traceId,
    isExpanded,
    isPopoutOpen,
    onToggleExpand,
    onTogglePopout,
    expandedSegments,
    setExpandedSegments,
    popoutSegment,
    setPopoutSegment,
    activeLineNumber,
    lineNumberPadding,
    onCopyPermalink,
    enableLineActions = false,
}: SegmentRendererProps): JSX.Element {
    if (segment.type === 'gen_expandable') {
        // Extract [GEN], [SPAN], or [EMBED] tag and rest of content
        const tagMatch = segment.content.match(/^(\[(?:GEN|SPAN|EMBED)\])\s*(.*)$/)
        const tag = tagMatch ? tagMatch[1] : segment.content
        const restContent = tagMatch ? tagMatch[2] : segment.content

        return (
            <span>
                <Link to={urls.llmAnalyticsTrace(traceId!, { event: segment.eventId })} title="Jump to event">
                    {tag}
                </Link>
                <button
                    onClick={() => onToggleExpand(index)}
                    className="text-link hover:underline cursor-pointer"
                    title={isExpanded ? 'Collapse' : 'Expand'}
                >
                    {isExpanded ? '[−]' : '[+]'}
                </button>{' '}
                {restContent.trim()}
                {isExpanded && (
                    <div className="ml-4 mt-2 mb-2 pl-4 border-l-2 border-border">
                        <NestedContentRenderer
                            content={segment.fullContent || ''}
                            traceId={traceId}
                            parentKey={`gen-${index}`}
                            expandedSegments={expandedSegments}
                            setExpandedSegments={setExpandedSegments}
                            popoutSegment={popoutSegment}
                            setPopoutSegment={setPopoutSegment}
                            activeLineNumber={activeLineNumber}
                            lineNumberPadding={lineNumberPadding}
                            onCopyPermalink={onCopyPermalink}
                            enableLineActions={enableLineActions}
                        />
                    </div>
                )}
            </span>
        )
    }

    if (segment.type === 'tools_expandable') {
        // Parse full content to split into individual tools
        const fullContent = segment.fullContent || ''
        const lines = fullContent.split('\n')

        // Find header line (e.g., "AVAILABLE TOOLS: 10")
        const headerLine = lines[0]
        const toolLines = lines.slice(1) // Skip header

        // Parse individual tool blocks (tool_name(), description, blank line)
        const toolBlocks: string[] = []
        let currentBlock: string[] = []

        for (const line of toolLines) {
            if (line.trim() === '' && currentBlock.length > 0) {
                // End of a tool block
                toolBlocks.push(currentBlock.join('\n'))
                currentBlock = []
            } else if (line.trim() !== '') {
                currentBlock.push(line)
            }
        }
        // Add last block if exists
        if (currentBlock.length > 0) {
            toolBlocks.push(currentBlock.join('\n'))
        }

        // Split into visible and remaining tools
        const visibleTools = toolBlocks.slice(0, VISIBLE_TOOLS_COUNT)
        const hiddenTools = toolBlocks.slice(VISIBLE_TOOLS_COUNT)

        return (
            <span>
                {headerLine}
                {'\n\n'}
                {visibleTools.map((toolBlock, i) => (
                    <span key={i}>
                        <TextWithLinks
                            text={toolBlock}
                            traceId={traceId}
                            activeLineNumber={activeLineNumber}
                            lineNumberPadding={lineNumberPadding}
                            onCopyPermalink={onCopyPermalink}
                            enableLineActions={enableLineActions}
                        />
                        {'\n\n'}
                    </span>
                ))}
                {hiddenTools.length > 0 && (
                    <>
                        <button
                            onClick={() => onToggleExpand(index)}
                            className="text-link hover:underline cursor-pointer"
                            title={isExpanded ? 'Collapse' : 'Expand'}
                        >
                            {isExpanded ? '[−]' : '[+]'} {hiddenTools.length} more tool
                            {hiddenTools.length > 1 ? 's' : ''}
                        </button>
                        {isExpanded && (
                            <div className="ml-4 mt-2 mb-2">
                                {hiddenTools.map((toolBlock, i) => (
                                    <span key={i}>
                                        <TextWithLinks
                                            text={toolBlock}
                                            traceId={traceId}
                                            activeLineNumber={activeLineNumber}
                                            lineNumberPadding={lineNumberPadding}
                                            onCopyPermalink={onCopyPermalink}
                                            enableLineActions={enableLineActions}
                                        />
                                        {'\n\n'}
                                    </span>
                                ))}
                            </div>
                        )}
                    </>
                )}
            </span>
        )
    }

    // Truncated segment
    return (
        <span>
            {isExpanded ? (
                <>
                    <TextWithLinks
                        text={segment.fullContent || ''}
                        traceId={traceId}
                        activeLineNumber={activeLineNumber}
                        lineNumberPadding={lineNumberPadding}
                        onCopyPermalink={onCopyPermalink}
                        enableLineActions={enableLineActions}
                    />
                    <button
                        onClick={() => onToggleExpand(index)}
                        className="text-link hover:underline cursor-pointer ml-1"
                    >
                        [collapse]
                    </button>
                </>
            ) : (
                <>
                    <button onClick={() => onToggleExpand(index)} className="text-link hover:underline cursor-pointer">
                        {segment.content}
                    </button>
                    <Tooltip
                        title={
                            isPopoutOpen ? (
                                <div
                                    data-popout-content
                                    className="max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs"
                                >
                                    {segment.fullContent}
                                </div>
                            ) : null
                        }
                        containerClassName="max-w-4xl"
                        placement="top"
                        visible={isPopoutOpen}
                    >
                        <button
                            data-popout-button
                            onClick={(e) => {
                                e.stopPropagation()
                                onTogglePopout(index)
                            }}
                            className="inline-flex items-center justify-center w-4 h-4 ml-1 text-muted hover:text-default transition-colors"
                            title="Preview truncated content"
                        >
                            <IconExternal className="w-3 h-3" />
                        </button>
                    </Tooltip>
                </>
            )}
        </span>
    )
}
