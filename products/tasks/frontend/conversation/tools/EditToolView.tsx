import { JSX, useEffect, useState } from 'react'

import { CodePreview } from '../primitives/CodePreview'
import { FileMentionChip } from '../primitives/FileMentionChip'
import { ICONS, IconPencil } from '../primitives/icons'
import {
    findDiffContent,
    LoadingIcon,
    StatusIndicators,
    ToolViewProps,
    useToolCallStatus,
} from '../primitives/toolCallUtils'

const ICON_SIZE = 12

/**
 * Line-level add/remove counts between two blobs, matched by line content (so a
 * moved line isn't double counted). Ported verbatim from the reference.
 */
function getDiffStats(
    oldText: string | null | undefined,
    newText: string | null | undefined
): { added: number; removed: number } {
    const oldLines = oldText ? oldText.split('\n') : []
    const newLines = newText ? newText.split('\n') : []

    if (!oldText) {
        return { added: newLines.length, removed: 0 }
    }

    const oldCounts = new Map<string, number>()
    for (const line of oldLines) {
        oldCounts.set(line, (oldCounts.get(line) ?? 0) + 1)
    }

    const newCounts = new Map<string, number>()
    for (const line of newLines) {
        newCounts.set(line, (newCounts.get(line) ?? 0) + 1)
    }

    let added = 0
    let removed = 0

    for (const [line, count] of newCounts) {
        const oldCount = oldCounts.get(line) ?? 0
        if (count > oldCount) {
            added += count - oldCount
        }
    }

    for (const [line, count] of oldCounts) {
        const newCount = newCounts.get(line) ?? 0
        if (count > newCount) {
            removed += count - newCount
        }
    }

    return { added, removed }
}

/**
 * Read-only renderer for `edit` tool calls. Shows the edited file as a one-line
 * header (file mention chip plus a `+added -removed` summary); clicking the
 * header toggles an inline unified diff via `CodePreview`. Plan files
 * (`claude/plans/…`) start collapsed.
 */
export function EditToolView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element {
    const { status, content, locations } = toolCall
    const { isLoading, isFailed, wasCancelled } = useToolCallStatus(status, turnCancelled, turnComplete)

    const diff = findDiffContent(content)
    const filePath = diff?.path ?? locations?.[0]?.path ?? ''
    const oldText = diff?.oldText
    const newText = diff?.newText
    const isNewFile = diff && !oldText
    const hasDiff = !!diff && (!!oldText || !!newText)
    const diffStats = diff ? getDiffStats(oldText, newText) : null

    const isPlanFile = filePath.includes('claude/plans/')
    const [isExpanded, setIsExpanded] = useState(!isPlanFile)

    useEffect(() => {
        if (isPlanFile) {
            setIsExpanded(false)
        }
    }, [isPlanFile])

    const CollapseIcon = ICONS.ArrowsInSimple
    const ExpandIcon = ICONS.ArrowsOutSimple

    return (
        <div className="max-w-4xl overflow-hidden rounded-lg border border-border">
            <button
                type="button"
                onClick={() => setIsExpanded(!isExpanded)}
                className="flex w-full cursor-pointer items-center justify-between border-none bg-transparent px-3 py-2"
            >
                <div className="flex items-center gap-2">
                    <LoadingIcon icon={IconPencil} isLoading={isLoading} />
                    {filePath && <FileMentionChip path={filePath} />}
                    {diffStats && (
                        <span className="font-mono text-[13px]">
                            <span className="text-success">+{diffStats.added}</span>{' '}
                            <span className="text-danger">-{diffStats.removed}</span>
                        </span>
                    )}
                    <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
                </div>
                {hasDiff && (
                    <span className="text-muted">
                        {isExpanded ? (
                            <CollapseIcon style={{ fontSize: ICON_SIZE }} />
                        ) : (
                            <ExpandIcon style={{ fontSize: ICON_SIZE }} />
                        )}
                    </span>
                )}
            </button>

            {isExpanded && hasDiff && (
                <CodePreview
                    content={newText ?? ''}
                    filePath={filePath}
                    oldContent={isNewFile ? null : (oldText ?? null)}
                    maxHeight="700px"
                    cacheKey={toolCall.toolCallId}
                />
            )}
        </div>
    )
}
