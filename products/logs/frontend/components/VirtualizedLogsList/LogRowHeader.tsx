import React from 'react'

import { ROW_GAP } from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { VirtualizedTableColumn } from 'products/logs/frontend/components/VirtualizedLogsList/types'
import { ParsedLogMessage } from 'products/logs/frontend/types'

export interface LogRowHeaderProps {
    columns: VirtualizedTableColumn<ParsedLogMessage>[]
    rowWidth: number
}

export function LogRowHeader({ columns, rowWidth }: LogRowHeaderProps): JSX.Element {
    const visibleColumns = columns.filter((col) => !col.isHidden)
    return (
        <div
            style={{ width: rowWidth, gap: ROW_GAP }}
            className="flex items-center h-8 border-b border-border bg-bg-3000 text-xs font-semibold text-muted sticky top-0 z-10"
        >
            {visibleColumns.map((col) => (
                <React.Fragment key={col.key}>{col.renderHeader ? col.renderHeader() : col.title}</React.Fragment>
            ))}
        </div>
    )
}
