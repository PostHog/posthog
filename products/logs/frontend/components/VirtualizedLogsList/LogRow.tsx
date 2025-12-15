import { IconChevronRight, IconPin, IconPinFilled, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import { ExpandedLogContent } from 'products/logs/frontend/components/LogsViewer/ExpandedLogContent'
import { LogsViewerRowActions } from 'products/logs/frontend/components/LogsViewer/LogsViewerRowActions'
import { AttributeCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/AttributeCell'
import { MessageCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/MessageCell'
import { ParsedLogMessage } from 'products/logs/frontend/types'

const DEFAULT_ATTRIBUTE_COLUMN_WIDTH = 150
const MIN_ATTRIBUTE_COLUMN_WIDTH = 80
const MAX_ATTRIBUTE_COLUMN_WIDTH = 500
export const RESIZER_HANDLE_WIDTH = 16 // Width of the ResizableElement handle

const SEVERITY_BAR_COLORS: Record<LogMessage['severity_text'], string> = {
    trace: 'bg-muted-alt',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-danger',
    fatal: 'bg-danger-dark',
}

// Fixed column widths
const SEVERITY_WIDTH = 8
const EXPAND_WIDTH = 28
const TIMESTAMP_WIDTH = 180
const MESSAGE_MIN_WIDTH = 300
const ACTIONS_WIDTH = 70
const FIXED_COLUMNS_TOTAL_WIDTH = SEVERITY_WIDTH + EXPAND_WIDTH + TIMESTAMP_WIDTH + ACTIONS_WIDTH

// Get width for an attribute column
export const getAttributeColumnWidth = (
    attributeKey: string,
    attributeColumnWidths: Record<string, number>
): number => {
    return attributeColumnWidths[attributeKey] ?? DEFAULT_ATTRIBUTE_COLUMN_WIDTH
}

// Calculate total width of attribute columns
const getTotalAttributeColumnsWidth = (
    attributeColumns: string[],
    attributeColumnWidths: Record<string, number>
): number => {
    return attributeColumns.reduce((sum, key) => sum + getAttributeColumnWidth(key, attributeColumnWidths), 0)
}

// Calculate total width of fixed-width columns (excludes message flex column)
export const getFixedColumnsWidth = (
    attributeColumns: string[] = [],
    attributeColumnWidths: Record<string, number> = {}
): number => {
    return FIXED_COLUMNS_TOTAL_WIDTH + getTotalAttributeColumnsWidth(attributeColumns, attributeColumnWidths)
}

// Calculate total minimum width for horizontal scrolling
export const getMinRowWidth = (
    attributeColumns: string[] = [],
    attributeColumnWidths: Record<string, number> = {}
): number => {
    return (
        FIXED_COLUMNS_TOTAL_WIDTH +
        MESSAGE_MIN_WIDTH +
        getTotalAttributeColumnsWidth(attributeColumns, attributeColumnWidths)
    )
}

export const LOG_ROW_HEADER_HEIGHT = 32

// Get flex style for the message column
const getMessageStyle = (flexWidth?: number): React.CSSProperties => ({
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: flexWidth ? Math.max(flexWidth, MESSAGE_MIN_WIDTH) : MESSAGE_MIN_WIDTH,
    minWidth: MESSAGE_MIN_WIDTH,
})

export interface LogRowProps {
    log: ParsedLogMessage
    logIndex: number
    isAtCursor: boolean
    isExpanded: boolean
    pinned: boolean
    showPinnedWithOpacity: boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'>
    onTogglePin: (log: ParsedLogMessage) => void
    onToggleExpand: () => void
    onSetCursor: () => void
    rowWidth?: number
    attributeColumns?: string[]
    attributeColumnWidths?: Record<string, number>
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
    onSetCursor,
    rowWidth,
    attributeColumns = [],
    attributeColumnWidths = {},
}: LogRowProps): JSX.Element {
    const isNew = 'new' in log && log.new
    const flexWidth = rowWidth
        ? rowWidth -
          getFixedColumnsWidth(attributeColumns, attributeColumnWidths) -
          attributeColumns.length * RESIZER_HANDLE_WIDTH
        : undefined

    const severityColor = SEVERITY_BAR_COLORS[log.severity_text] ?? 'bg-muted-3000'

    return (
        <div className={cn('border-b border-border', isNew && 'VirtualizedLogsList__row--new')}>
            <div
                className={cn(
                    'flex items-center gap-2 cursor-pointer hover:bg-fill-highlight-100 group',
                    isAtCursor && 'bg-primary-highlight',
                    pinned && 'bg-warning-highlight',
                    pinned && showPinnedWithOpacity && 'opacity-50'
                )}
                onMouseDown={onSetCursor}
            >
                {/* Severity + Expand (grouped, no gap) */}
                <div className="flex items-center self-stretch">
                    <Tooltip title={log.severity_text.toUpperCase()}>
                        <div
                            className="flex items-stretch self-stretch"
                            style={{ width: SEVERITY_WIDTH, flexShrink: 0 }}
                        >
                            <div className={cn('w-1 rounded-full', severityColor)} />
                        </div>
                    </Tooltip>
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
                    const attrValue = log.attributes[attributeKey]
                    return (
                        <AttributeCell
                            key={attributeKey}
                            attributeKey={attributeKey}
                            value={attrValue != null ? String(attrValue) : '-'}
                            width={getAttributeColumnWidth(attributeKey, attributeColumnWidths) + RESIZER_HANDLE_WIDTH}
                        />
                    )
                })}

                {/* Message */}
                <MessageCell
                    message={log.cleanBody}
                    wrapBody={wrapBody}
                    prettifyJson={prettifyJson}
                    parsedBody={log.parsedBody}
                    style={getMessageStyle(flexWidth)}
                />

                {/* Actions */}
                <div className="flex items-center gap-1 justify-end shrink-0 px-1" style={{ width: ACTIONS_WIDTH }}>
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={pinned ? <IconPinFilled /> : <IconPin />}
                        onMouseDown={(e) => {
                            e.stopPropagation()
                            onTogglePin(log)
                        }}
                        tooltip={pinned ? 'Unpin log' : 'Pin log'}
                        className={cn(pinned ? 'text-warning' : 'text-muted opacity-0 group-hover:opacity-100')}
                    />
                    <div className="opacity-0 group-hover:opacity-100" onMouseDown={(e) => e.stopPropagation()}>
                        <LogsViewerRowActions log={log} />
                    </div>
                </div>
            </div>
            {isExpanded && <ExpandedLogContent log={log} logIndex={logIndex} />}
        </div>
    )
}

export interface LogRowHeaderProps {
    rowWidth: number
    attributeColumns?: string[]
    attributeColumnWidths?: Record<string, number>
    onRemoveAttributeColumn?: (attributeKey: string) => void
    onResizeAttributeColumn?: (attributeKey: string, width: number) => void
}

export function LogRowHeader({
    rowWidth,
    attributeColumns = [],
    attributeColumnWidths = {},
    onRemoveAttributeColumn,
    onResizeAttributeColumn,
}: LogRowHeaderProps): JSX.Element {
    const flexWidth =
        rowWidth -
        getFixedColumnsWidth(attributeColumns, attributeColumnWidths) -
        attributeColumns.length * RESIZER_HANDLE_WIDTH

    return (
        <div
            className="flex items-center gap-2 h-8 border-b border-border bg-bg-3000 text-xs font-semibold text-muted sticky top-0 z-10"
            style={{ width: rowWidth }}
        >
            {/* Severity + Expand (grouped, no gap, no labels) */}
            <div
                className="flex items-center self-stretch"
                style={{ width: SEVERITY_WIDTH + EXPAND_WIDTH, flexShrink: 0 }}
            />

            {/* Timestamp */}
            <div className="flex items-center pr-3" style={{ width: TIMESTAMP_WIDTH, flexShrink: 0 }}>
                Timestamp
            </div>

            {/* Attribute columns */}
            {attributeColumns.map((attributeKey) => {
                const width = getAttributeColumnWidth(attributeKey, attributeColumnWidths)
                return (
                    <ResizableElement
                        key={`attr-${attributeKey}`}
                        defaultWidth={width + RESIZER_HANDLE_WIDTH}
                        minWidth={MIN_ATTRIBUTE_COLUMN_WIDTH + RESIZER_HANDLE_WIDTH}
                        maxWidth={MAX_ATTRIBUTE_COLUMN_WIDTH + RESIZER_HANDLE_WIDTH}
                        onResize={(newWidth) =>
                            onResizeAttributeColumn?.(attributeKey, newWidth - RESIZER_HANDLE_WIDTH)
                        }
                        className="flex items-center h-full shrink-0 group/header"
                        innerClassName="h-full"
                    >
                        <div className="flex items-center pr-3 gap-1 h-full w-full">
                            <span className="truncate flex-1" title={attributeKey}>
                                {attributeKey}
                            </span>
                            {onRemoveAttributeColumn && (
                                <LemonButton
                                    size="xsmall"
                                    noPadding
                                    icon={<IconX className="text-muted" />}
                                    onClick={() => onRemoveAttributeColumn(attributeKey)}
                                    tooltip="Remove column"
                                    className="opacity-0 group-hover/header:opacity-100 shrink-0"
                                />
                            )}
                        </div>
                    </ResizableElement>
                )
            })}

            {/* Message */}
            <div className="flex items-center px-1" style={getMessageStyle(flexWidth)}>
                Message
            </div>

            {/* Actions (no label) */}
            <div className="flex items-center px-1" style={{ width: ACTIONS_WIDTH, flexShrink: 0 }} />
        </div>
    )
}
