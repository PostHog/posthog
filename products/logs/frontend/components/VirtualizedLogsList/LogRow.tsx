import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import { ExpandedLogContent } from 'products/logs/frontend/components/LogsViewer/ExpandedLogContent'
import { LogRowFAB } from 'products/logs/frontend/components/LogsViewer/LogRowFAB/LogRowFAB'
import { AttributeCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/AttributeCell'
import { MessageCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/MessageCell'
import {
    CHECKBOX_WIDTH,
    EXPAND_WIDTH,
    RESIZER_HANDLE_WIDTH,
    ROW_GAP,
    SEVERITY_WIDTH,
    TIMESTAMP_WIDTH,
    getAttributeColumnWidth,
    getFixedColumnsWidth,
    getMessageStyle,
} from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { ParsedLogMessage } from 'products/logs/frontend/types'

const SEVERITY_BAR_COLORS: Record<LogMessage['severity_text'], string> = {
    trace: 'bg-muted-alt',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-danger',
    fatal: 'bg-danger-dark',
}

export interface LogRowProps {
    log: ParsedLogMessage
    logIndex: number
    isAtCursor: boolean
    isExpanded: boolean
    pinned: boolean
    showPinnedWithOpacity: boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime' | 'displayTimezone'>
    onTogglePin: (log: ParsedLogMessage) => void
    onToggleExpand: () => void
    onClick?: () => void
    rowWidth?: number
    attributeColumns?: string[]
    attributeColumnWidths?: Record<string, number>
    // Selection
    isSelected?: boolean
    onToggleSelect?: () => void
    onShiftClick?: (logIndex: number) => void
    // Per-row prettify
    isPrettified?: boolean
    onTogglePrettify?: (log: ParsedLogMessage) => void
    minHeight?: number
}

export function LogRow({
    log,
    logIndex,
    isAtCursor,
    isExpanded,
    pinned,
    showPinnedWithOpacity,
    wrapBody,
    prettifyJson,
    tzLabelFormat,
    onTogglePin,
    onToggleExpand,
    onClick,
    rowWidth,
    attributeColumns = [],
    attributeColumnWidths = {},
    isSelected = false,
    onToggleSelect,
    onShiftClick,
    isPrettified = false,
    onTogglePrettify,
    minHeight = 32,
}: LogRowProps): JSX.Element {
    const isNew = 'new' in log && log.new
    const flexWidth = rowWidth
        ? rowWidth -
          getFixedColumnsWidth(attributeColumns, attributeColumnWidths) -
          attributeColumns.length * RESIZER_HANDLE_WIDTH
        : undefined

    const severityColor = SEVERITY_BAR_COLORS[log.severity_text] ?? 'bg-muted-3000'

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
                <div className="flex items-center self-stretch">
                    <Tooltip title={log.severity_text.toUpperCase()}>
                        <div
                            className="flex items-stretch self-stretch"
                            style={{ width: SEVERITY_WIDTH, flexShrink: 0 }}
                        >
                            <div className={cn('w-1 rounded-full', severityColor)} />
                        </div>
                    </Tooltip>
                    <div className="flex items-center justify-center shrink-0" style={{ width: CHECKBOX_WIDTH }}>
                        <LemonCheckbox
                            checked={isSelected}
                            onChange={() => onToggleSelect?.()}
                            stopPropagation
                            size="small"
                        />
                    </div>
                    <div
                        className="flex items-stretch self-stretch justify-center"
                        style={{ width: EXPAND_WIDTH, flexShrink: 0 }}
                    >
                        <LemonButton
                            size="xsmall"
                            icon={
                                <IconChevronRight className={cn('transition-transform', isExpanded && 'rotate-90')} />
                            }
                            onMouseDown={(e) => {
                                e.stopPropagation()
                                onToggleExpand()
                            }}
                            onClick={(e) => e.stopPropagation()}
                        />
                    </div>
                </div>

                {/* Timestamp */}
                <div className="flex items-center shrink-0" style={{ width: TIMESTAMP_WIDTH }}>
                    <span className="text-xs text-muted font-mono">
                        <TZLabel time={log.timestamp} {...tzLabelFormat} timestampStyle="absolute" />
                    </span>
                </div>

                {/* Attribute columns */}
                {attributeColumns.map((attributeKey) => {
                    const attrValue = log.attributes[attributeKey] ?? log.resource_attributes[attributeKey]
                    return (
                        <AttributeCell
                            key={attributeKey}
                            attributeKey={attributeKey}
                            value={attrValue != null ? String(attrValue) : ''}
                            width={getAttributeColumnWidth(attributeKey, attributeColumnWidths) + RESIZER_HANDLE_WIDTH}
                        />
                    )
                })}

                {/* Message */}
                <MessageCell
                    message={log.cleanBody}
                    wrapBody={isPrettified || wrapBody}
                    prettifyJson={isPrettified || prettifyJson}
                    parsedBody={log.parsedBody}
                    style={getMessageStyle(flexWidth)}
                />

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
