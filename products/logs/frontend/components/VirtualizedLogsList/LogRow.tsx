import { IconChevronRight, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import { ExpandedLogContent } from 'products/logs/frontend/components/LogsViewer/ExpandedLogContent'
import { LogsViewerRowActions } from 'products/logs/frontend/components/LogsViewer/LogsViewerRowActions'
import { ParsedLogMessage } from 'products/logs/frontend/types'

const SEVERITY_BAR_COLORS: Record<LogMessage['severity_text'], string> = {
    trace: 'bg-muted',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-destructive',
    fatal: 'bg-destructive-strong',
}

export interface LogColumnConfig {
    key: string
    label?: string
    width?: number
    minWidth?: number
    flex?: number
}

export const LOG_COLUMNS: LogColumnConfig[] = [
    { key: 'severity', width: 8 },
    { key: 'expand', width: 24 },
    { key: 'timestamp', label: 'Timestamp', width: 180 },
    { key: 'message', label: 'Message', minWidth: 300, flex: 1 },
    { key: 'actions', width: 70 },
]

// Calculate total width of fixed-width columns (excludes flex columns)
export const getFixedColumnsWidth = (): number => {
    return LOG_COLUMNS.reduce((sum, c) => sum + (c.width || 0), 0)
}

// Calculate total minimum width for horizontal scrolling
export const getMinRowWidth = (): number => {
    return LOG_COLUMNS.reduce((sum, col) => sum + (col.width || col.minWidth || 100), 0)
}

export const LOG_ROW_HEADER_HEIGHT = 32

// Get cell style based on column config and available flex width
const getCellStyle = (column: LogColumnConfig, flexWidth?: number): React.CSSProperties => {
    return column.flex
        ? {
              flexGrow: column.flex,
              flexShrink: 1,
              flexBasis: flexWidth ? Math.max(flexWidth, column.minWidth || 0) : column.minWidth,
              minWidth: column.minWidth,
          }
        : { width: column.width, flexShrink: 0 }
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
}: LogRowProps): JSX.Element {
    const isNew = 'new' in log && log.new
    const flexWidth = rowWidth ? rowWidth - getFixedColumnsWidth() : undefined

    const renderCell = (column: LogColumnConfig): JSX.Element => {
        const cellStyle = getCellStyle(column, flexWidth)

        switch (column.key) {
            case 'severity': {
                const severityColor = SEVERITY_BAR_COLORS[log.severity_text] ?? 'bg-muted-3000'
                return (
                    <Tooltip key={column.key} title={log.severity_text.toUpperCase()}>
                        <div className="flex items-stretch self-stretch w-2" style={{ flexShrink: 0 }}>
                            <div className={cn('w-1 rounded-full', severityColor)} />
                        </div>
                    </Tooltip>
                )
            }
            case 'expand':
                return (
                    <div key={column.key} style={cellStyle} className="flex items-center justify-center">
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={
                                <IconChevronRight className={cn('transition-transform', isExpanded && 'rotate-90')} />
                            }
                            onClick={(e) => {
                                e.stopPropagation()
                                onToggleExpand()
                            }}
                        />
                    </div>
                )
            case 'timestamp':
                return (
                    <div key={column.key} style={cellStyle} className="flex items-center shrink-0">
                        <span className="text-xs text-muted-foreground font-mono">
                            <TZLabel time={log.timestamp} {...tzLabelFormat} timestampStyle="absolute" />
                        </span>
                    </div>
                )
            case 'message': {
                const isPrettyJson = prettifyJson && log.parsedBody
                const content = isPrettyJson ? JSON.stringify(log.parsedBody, null, 2) : log.cleanBody

                if (isPrettyJson) {
                    return (
                        <div
                            key={column.key}
                            style={cellStyle}
                            className={cn('flex items-start py-1.5', wrapBody ? 'overflow-hidden' : 'overflow-x-auto')}
                        >
                            <pre className={cn('font-mono text-xs m-0', !wrapBody && 'whitespace-nowrap')}>
                                {content}
                            </pre>
                        </div>
                    )
                }

                return (
                    <div
                        key={column.key}
                        style={cellStyle}
                        className={cn('flex items-start py-1.5', wrapBody ? 'overflow-hidden' : 'overflow-x-auto')}
                    >
                        <span
                            className={cn(
                                'font-mono text-xs',
                                wrapBody ? 'whitespace-pre-wrap break-all' : 'whitespace-nowrap'
                            )}
                        >
                            {content}
                        </span>
                    </div>
                )
            }
            case 'actions':
                return (
                    <div
                        key={column.key}
                        style={cellStyle}
                        className="flex items-center gap-1 justify-end shrink-0 px-1"
                    >
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={pinned ? <IconPinFilled /> : <IconPin />}
                            onClick={(e) => {
                                e.stopPropagation()
                                onTogglePin(log)
                            }}
                            tooltip={pinned ? 'Unpin log' : 'Pin log'}
                            className={cn(
                                pinned ? 'text-warning' : 'text-muted-foreground opacity-0 group-hover:opacity-100'
                            )}
                        />
                        <div className="opacity-0 group-hover:opacity-100" onClick={(e) => e.stopPropagation()}>
                            <LogsViewerRowActions log={log} />
                        </div>
                    </div>
                )
            default:
                return <div key={column.key} style={cellStyle} />
        }
    }

    return (
        <div className={cn('border-b border-border', isNew && 'VirtualizedLogsList__row--new')}>
            <div
                className={cn(
                    'flex items-center cursor-pointer hover:bg-fill-highlight-100 group',
                    isAtCursor && 'bg-primary-highlight',
                    pinned && 'bg-warning-highlight',
                    pinned && showPinnedWithOpacity && 'opacity-50'
                )}
                onClick={onSetCursor}
            >
                {LOG_COLUMNS.map(renderCell)}
            </div>
            {isExpanded && <ExpandedLogContent log={log} logIndex={logIndex} />}
        </div>
    )
}

export function LogRowHeader({ rowWidth }: { rowWidth: number }): JSX.Element {
    const flexWidth = rowWidth - getFixedColumnsWidth()

    return (
        <div
            className="flex items-center h-8 border-b border-border bg-card text-xs font-semibold text-muted-foreground sticky top-0 z-10"
            style={{ width: rowWidth }}
        >
            {LOG_COLUMNS.map((column) => (
                <div key={column.key} style={getCellStyle(column, flexWidth)} className="flex items-center px-1">
                    {column.label || ''}
                </div>
            ))}
        </div>
    )
}
