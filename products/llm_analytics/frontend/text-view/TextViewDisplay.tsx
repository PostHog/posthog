/**
 * Text view display component for generation events
 * Shows a formatted text representation with copy functionality and expandable truncated sections
 */
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { teamLogic } from 'scenes/teamLogic'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { SegmentRenderer, TextWithLinks } from './components'
import { calculateLineNumberPadding, getExpandedTreeText, getPlainText, parseTextSegments } from './parsing'
import { textViewLogic } from './textViewLogic'

interface TraceTreeNode {
    event: LLMTraceEvent
    children?: TraceTreeNode[]
}

export function TextViewDisplay({
    event,
    trace,
    tree,
    onFallback,
    lineNumber,
    onCopyPermalink,
}: {
    event?: LLMTraceEvent
    trace?: LLMTrace
    tree?: TraceTreeNode[]
    onFallback?: () => void
    lineNumber?: number | null
    onCopyPermalink?: (lineNumber: number) => void
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)

    // Use Kea logic for text representation fetching and UI state
    const { textRepr, textReprLoading, copied, expandedSegments, popoutSegment } = useValues(
        textViewLogic({ trace, event, tree, teamId: currentTeamId, onFallback })
    )
    const { fetchTextRepr, setCopied, toggleSegment, setExpandedSegments, setPopoutSegment } = useActions(
        textViewLogic({ trace, event, tree, teamId: currentTeamId, onFallback })
    )

    // Get trace ID for event links
    const traceId = trace?.id

    // Fetch text representation when component mounts or key props change
    useEffect(() => {
        fetchTextRepr()
    }, [event?.id, trace?.id, fetchTextRepr])

    // Close popout when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent): void => {
            if (popoutSegment !== null) {
                const target = event.target as HTMLElement
                if (!target.closest('[data-popout-content]') && !target.closest('[data-popout-button]')) {
                    setPopoutSegment(null)
                }
            }
        }

        if (popoutSegment !== null) {
            document.addEventListener('mousedown', handleClickOutside)
            return () => {
                document.removeEventListener('mousedown', handleClickOutside)
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- setPopoutSegment is a stable Kea action
    }, [popoutSegment])

    const segments = useMemo(() => parseTextSegments(textRepr || ''), [textRepr])
    const lineNumberPadding = useMemo(() => calculateLineNumberPadding(textRepr || ''), [textRepr])

    // Get indices of all expandable segments
    const allExpandableIndices = segments
        .map((seg, idx) =>
            seg.type === 'truncated' || seg.type === 'gen_expandable' || seg.type === 'tools_expandable' ? idx : -1
        )
        .filter((idx) => idx !== -1)

    const allExpanded =
        allExpandableIndices.length > 0 && allExpandableIndices.every((idx) => expandedSegments.has(idx))

    const handleCopy = (): void => {
        // Check if we have gen_expandable segments (trace view)
        const hasGenExpandable = segments.some((seg) => seg.type === 'gen_expandable')

        // For trace views, copy the full expanded tree with truncation markers
        // For single events, copy the plain text as-is
        const textToCopy = hasGenExpandable ? getExpandedTreeText(segments) : getPlainText(segments)

        copyToClipboard(textToCopy, 'generation text')
        setCopied(true)
    }

    const handleToggleSegment = (index: number): void => {
        toggleSegment(index)
    }

    const toggleExpandAll = (): void => {
        if (allExpanded) {
            setExpandedSegments(new Set())
        } else {
            setExpandedSegments(new Set(allExpandableIndices))
        }
    }

    const handleTogglePopout = (index: number): void => {
        setPopoutSegment(popoutSegment === index ? null : index)
    }

    if (textReprLoading) {
        return (
            <div className="flex items-center justify-center p-8 bg-bg-light rounded border border-border">
                <Spinner className="text-2xl" />
                <span className="ml-2">Loading text representation...</span>
            </div>
        )
    }

    return (
        <div className="relative flex flex-col flex-1 min-h-0">
            <div className="absolute top-2 right-2 z-10 flex gap-2">
                {allExpandableIndices.length > 0 && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={toggleExpandAll}
                        tooltip={allExpanded ? 'Collapse all expandable sections' : 'Expand all expandable sections'}
                    >
                        {allExpanded ? 'Collapse all' : 'Expand all'}
                    </LemonButton>
                )}
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconCopy />}
                    onClick={handleCopy}
                    tooltip={copied ? 'Copied!' : 'Copy text representation'}
                >
                    {copied ? 'Copied!' : 'Copy text'}
                </LemonButton>
            </div>
            <pre className="font-mono text-xs whitespace-pre-wrap p-4 bg-bg-light rounded border border-border overflow-auto flex-1 min-h-0 max-h-[200vh]">
                {segments.map((segment, index) => {
                    if (segment.type === 'text') {
                        // Trim trailing whitespace if followed by gen_expandable
                        const nextSegment = segments[index + 1]
                        const content =
                            nextSegment?.type === 'gen_expandable' ? segment.content.trimEnd() : segment.content
                        return (
                            <span key={index}>
                                <TextWithLinks
                                    text={content}
                                    traceId={traceId}
                                    activeLineNumber={lineNumber}
                                    lineNumberPadding={lineNumberPadding}
                                    onCopyPermalink={onCopyPermalink}
                                    enableLineActions
                                />
                            </span>
                        )
                    }

                    // Render expandable segments (truncated, gen_expandable, tools_expandable)
                    return (
                        <SegmentRenderer
                            key={index}
                            segment={segment}
                            index={index}
                            traceId={traceId}
                            isExpanded={expandedSegments.has(index)}
                            isPopoutOpen={popoutSegment === index}
                            onToggleExpand={handleToggleSegment}
                            onTogglePopout={handleTogglePopout}
                            expandedSegments={expandedSegments}
                            setExpandedSegments={setExpandedSegments}
                            popoutSegment={popoutSegment}
                            setPopoutSegment={setPopoutSegment}
                            activeLineNumber={lineNumber}
                            lineNumberPadding={lineNumberPadding}
                            enableLineActions
                        />
                    )
                })}
            </pre>
        </div>
    )
}
