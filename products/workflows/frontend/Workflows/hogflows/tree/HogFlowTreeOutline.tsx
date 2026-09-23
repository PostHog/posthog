import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { ScrollArea, ScrollBar } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { HogFlowTreeOutlineRow } from './HogFlowTreeOutlineRow'
import { filterWorkflowTreeOutline, type WorkflowTreeOutlineRow as OutlineRow } from './workflowTreeOutline'

export function HogFlowTreeOutline({
    rows,
    activeTargetId,
    onSelectRow,
    onSetAllPathsHidden,
    className,
}: {
    rows: OutlineRow[]
    activeTargetId: string | null
    onSelectRow: (row: OutlineRow) => void
    onSetAllPathsHidden: (hidden: boolean) => void
    className?: string
}): JSX.Element {
    const [query, setQuery] = useState('')
    const visibleRows = filterWorkflowTreeOutline(rows, query)

    return (
        <nav
            aria-label="Workflow outline"
            className={cn('flex min-h-0 min-w-0 flex-col', className)}
            data-attr="workflow-tree-outline"
        >
            <div className="flex flex-col gap-2 border-b p-2">
                <LemonInput
                    type="search"
                    size="xsmall"
                    placeholder="Find a step"
                    value={query}
                    onChange={setQuery}
                    data-attr="workflow-tree-outline-filter"
                />
                <div className="flex flex-wrap gap-1">
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={() => onSetAllPathsHidden(false)}
                        data-attr="workflow-tree-outline-show-all"
                    >
                        Show all paths
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={() => onSetAllPathsHidden(true)}
                        data-attr="workflow-tree-outline-hide-all"
                    >
                        Hide all paths
                    </LemonButton>
                </div>
            </div>
            <ScrollArea className="min-h-0 flex-1" data-quill>
                {visibleRows.length === 0 ? (
                    <p className="m-0 p-3 text-xs text-secondary">No step matches your search.</p>
                ) : (
                    <ul className="m-0 flex flex-col p-1">
                        {visibleRows.map((row) => (
                            <HogFlowTreeOutlineRow
                                key={row.key}
                                row={row}
                                active={row.targetId === activeTargetId}
                                onSelect={onSelectRow}
                            />
                        ))}
                    </ul>
                )}
                <ScrollBar orientation="vertical" />
            </ScrollArea>
        </nav>
    )
}
