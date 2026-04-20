import React from 'react'

import { cn } from 'lib/utils/css-classes'

import { ExpandedLogContent } from 'products/logs/frontend/components/LogsViewer/ExpandedLogContent'
import { LogRowFAB } from 'products/logs/frontend/components/LogsViewer/LogRowFAB/LogRowFAB'
import { ROW_GAP } from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { VirtualizedTableColumn } from 'products/logs/frontend/components/VirtualizedLogsList/types'
import { ParsedLogMessage } from 'products/logs/frontend/types'

export interface LogRowProps {
    log: ParsedLogMessage
    logIndex: number
    columns: VirtualizedTableColumn<ParsedLogMessage>[]
    isAtCursor: boolean
    isExpanded: boolean
    pinned: boolean
    showPinnedWithOpacity: boolean
    wrapBody: boolean
    onTogglePin: (log: ParsedLogMessage) => void
    onClick?: () => void
    rowWidth?: number
    // Selection
    onShiftClick?: (logIndex: number) => void
    isSelected?: boolean
    // Per-row prettify (for FAB)
    isPrettified?: boolean
    onTogglePrettify?: (log: ParsedLogMessage) => void
    minHeight?: number
}

export function LogRow({
    log,
    logIndex,
    columns,
    isAtCursor,
    isExpanded,
    pinned,
    showPinnedWithOpacity,
    wrapBody,
    onTogglePin,
    onClick,
    rowWidth,
    onShiftClick,
    isSelected = false,
    isPrettified = false,
    onTogglePrettify,
    minHeight = 32,
}: LogRowProps): JSX.Element {
    const isNew = 'new' in log && log.new

    const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>): void => {
        // Only handle shift+click here to prevent text selection during range select
        if (e.shiftKey && onShiftClick) {
            e.preventDefault()
            onShiftClick(logIndex)
        }
    }

    const handleClick = (e: React.MouseEvent<HTMLDivElement>): void => {
        // Don't trigger if user selected text
        const selection = window.getSelection()
        if (selection && selection.toString().length > 0) {
            return
        }
        // Skip row click if clicking on a link/button (e.g., ViewRecordingButton)
        if ((e.target as HTMLElement).closest('a, button')) {
            return
        }
        if (!e.shiftKey) {
            onClick?.()
        }
    }

    return (
        <div
            className={cn('border-b border-border', isNew && 'VirtualizedLogsList__row--new')}
            style={{ minWidth: rowWidth, minHeight }}
        >
            <div
                style={{ gap: ROW_GAP, minHeight }}
                className={cn(
                    'relative flex items-center cursor-pointer hover:bg-fill-highlight-100 group h-full',
                    isSelected && 'bg-fill-highlight-100',
                    isAtCursor && 'bg-primary-highlight',
                    pinned && showPinnedWithOpacity && 'bg-warning-highlight opacity-50'
                )}
                onMouseDown={handleMouseDown}
                onClick={handleClick}
            >
                {columns
                    .filter((col) => !col.isHidden)
                    .map((col) => (
                        <React.Fragment key={col.key}>{col.render(log, logIndex)}</React.Fragment>
                    ))}

                {/* Actions FAB */}
                <LogRowFAB
                    log={log}
                    pinned={pinned}
                    isPrettified={isPrettified}
                    onTogglePin={onTogglePin}
                    onTogglePrettify={onTogglePrettify}
                    showScrollButtons={!wrapBody}
                />
            </div>
            {isExpanded && <ExpandedLogContent log={log} />}
        </div>
    )
}
