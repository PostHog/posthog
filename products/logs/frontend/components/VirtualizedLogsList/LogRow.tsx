import { IconBrackets, IconChevronRight, IconPin, IconPinFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import { ExpandedLogContent } from 'products/logs/frontend/components/LogsViewer/ExpandedLogContent'
import { LogsViewerRowActions } from 'products/logs/frontend/components/LogsViewer/LogsViewerRowActions'
import { AttributeCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/AttributeCell'
import { MessageCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/MessageCell'
import {
    ACTIONS_WIDTH,
    CHECKBOX_WIDTH,
    EXPAND_WIDTH,
    MIN_ATTRIBUTE_COLUMN_WIDTH,
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
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'>
    onTogglePin: (log: ParsedLogMessage) => void
    onToggleExpand: () => void
    onSetCursor: () => void
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
    isSelected = false,
    onToggleSelect,
    onShiftClick,
    isPrettified = false,
    onTogglePrettify,
}: LogRowProps): JSX.Element {
    const isNew = 'new' in log && log.new
    const flexWidth = rowWidth
        ? rowWidth -
          getFixedColumnsWidth(attributeColumns, attributeColumnWidths) -
          attributeColumns.length * RESIZER_HANDLE_WIDTH
        : undefined

    const severityColor = SEVERITY_BAR_COLORS[log.severity_text] ?? 'bg-muted-3000'

    const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>): void => {
        if (e.shiftKey && onShiftClick) {
            e.preventDefault()
            onShiftClick(logIndex)
        } else {
            onSetCursor()
        }
    }

    return (
        <div
            className={cn('border-b border-border', isNew && 'VirtualizedLogsList__row--new')}
            style={{ minWidth: rowWidth }}
        >
            <div
                style={{ gap: ROW_GAP }}
                className={cn(
                    'flex items-center cursor-pointer hover:bg-fill-highlight-100 group',
                    isSelected && 'bg-fill-highlight-100',
                    isAtCursor && 'bg-primary-highlight',
                    pinned && 'bg-warning-highlight',
                    pinned && showPinnedWithOpacity && 'opacity-50'
                )}
                onMouseDown={handleMouseDown}
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
                            value={attrValue != null ? String(attrValue) : '-'}
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

                {/* Actions */}
                <div className="flex items-center gap-1 justify-end shrink-0 px-1" style={{ width: ACTIONS_WIDTH }}>
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconBrackets />}
                        onClick={(e) => {
                            e.preventDefault()
                            onTogglePrettify?.(log)
                        }}
                        onMouseDown={(e) => e.stopPropagation()}
                        tooltip={isPrettified ? 'Collapse JSON' : 'Prettify JSON'}
                        className={cn(
                            isPrettified ? 'text-brand-blue' : 'text-muted opacity-0 group-hover:opacity-100'
                        )}
                    />
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={pinned ? <IconPinFilled /> : <IconPin />}
                        onClick={(e) => {
                            e.preventDefault()
                            onTogglePin(log)
                        }}
                        onMouseDown={(e) => e.stopPropagation()}
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
    // Selection
    selectedCount?: number
    totalCount?: number
    onSelectAll?: () => void
    onClearSelection?: () => void
}

export function LogRowHeader({
    rowWidth,
    attributeColumns = [],
    attributeColumnWidths = {},
    onRemoveAttributeColumn,
    onResizeAttributeColumn,
    selectedCount = 0,
    totalCount = 0,
    onSelectAll,
    onClearSelection,
}: LogRowHeaderProps): JSX.Element {
    const flexWidth =
        rowWidth -
        getFixedColumnsWidth(attributeColumns, attributeColumnWidths) -
        attributeColumns.length * RESIZER_HANDLE_WIDTH

    const allSelected = totalCount > 0 && selectedCount === totalCount
    const someSelected = selectedCount > 0 && selectedCount < totalCount

    return (
        <div
            style={{ width: rowWidth, gap: ROW_GAP }}
            className="flex items-center h-8 border-b border-border bg-bg-3000 text-xs font-semibold text-muted sticky top-0 z-10"
        >
            {/* Severity + Checkbox + Expand header space */}
            <div className="flex items-center self-stretch">
                <div style={{ width: SEVERITY_WIDTH, flexShrink: 0 }} />
                <div className="flex items-center justify-center shrink-0" style={{ width: CHECKBOX_WIDTH }}>
                    <LemonCheckbox
                        checked={someSelected ? 'indeterminate' : allSelected}
                        onChange={() => (allSelected ? onClearSelection?.() : onSelectAll?.())}
                        size="small"
                    />
                </div>
                <div style={{ width: EXPAND_WIDTH, flexShrink: 0 }} />
            </div>

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
                        maxWidth={Infinity}
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
