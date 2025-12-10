import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { IconChevronLeft, IconChevronRight, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import { ExpandedLogContent } from 'products/logs/frontend/components/LogsViewer/ExpandedLogContent'
import { LogsViewerRowActions } from 'products/logs/frontend/components/LogsViewer/LogsViewerRowActions'
import { ParsedLogMessage } from 'products/logs/frontend/types'

import { virtualizedLogsListLogic } from './virtualizedLogsListLogic'

const SCROLL_INTERVAL_MS = 16 // ~60fps
const SCROLL_AMOUNT_PX = 8

const SEVERITY_BAR_COLORS: Record<LogMessage['severity_text'], string> = {
    trace: 'bg-muted-alt',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-danger',
    fatal: 'bg-danger-dark',
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
    { key: 'expand', width: 28 },
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
    const { messageScrollLeft } = useValues(virtualizedLogsListLogic)
    const { setMessageScrollLeft } = useActions(virtualizedLogsListLogic)

    const isNew = 'new' in log && log.new
    const flexWidth = rowWidth ? rowWidth - getFixedColumnsWidth() : undefined
    const messageScrollRef = useRef<HTMLDivElement>(null)
    const isProgrammaticScrollRef = useRef(false)

    // Sync scroll position from shared state (programmatic scroll)
    useEffect(() => {
        const el = messageScrollRef.current
        if (el && Math.abs(el.scrollLeft - messageScrollLeft) > 1) {
            isProgrammaticScrollRef.current = true
            el.scrollLeft = messageScrollLeft
            requestAnimationFrame(() => {
                isProgrammaticScrollRef.current = false
            })
        }
    }, [messageScrollLeft])

    const handleMessageScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        if (isProgrammaticScrollRef.current) {
            return
        }
        setMessageScrollLeft(e.currentTarget.scrollLeft)
    }

    const scrollIntervalRef = useRef<number | null>(null)

    const scrollMessage = useCallback(
        (direction: 'left' | 'right'): void => {
            const el = messageScrollRef.current
            if (el) {
                const newScrollLeft =
                    direction === 'left'
                        ? Math.max(0, el.scrollLeft - SCROLL_AMOUNT_PX)
                        : el.scrollLeft + SCROLL_AMOUNT_PX
                el.scrollLeft = newScrollLeft
                setMessageScrollLeft(newScrollLeft)
            }
        },
        [setMessageScrollLeft]
    )

    const startScrolling = useCallback(
        (direction: 'left' | 'right'): void => {
            if (scrollIntervalRef.current !== null) {
                return // Already scrolling
            }
            scrollMessage(direction) // Immediate first scroll
            scrollIntervalRef.current = window.setInterval(() => {
                scrollMessage(direction)
            }, SCROLL_INTERVAL_MS)
        },
        [scrollMessage]
    )

    const stopScrolling = useCallback((): void => {
        if (scrollIntervalRef.current) {
            clearInterval(scrollIntervalRef.current)
            scrollIntervalRef.current = null
        }
    }, [])

    // Cleanup interval on unmount
    useEffect(() => () => stopScrolling(), [])

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
                    <div key={column.key} style={cellStyle} className="flex items-stretch self-stretch justify-center">
                        <LemonButton
                            size="xsmall"
                            icon={
                                <IconChevronRight className={cn('transition-transform', isExpanded && 'rotate-90')} />
                            }
                            onMouseDown={(e) => {
                                e.stopPropagation()
                                onToggleExpand()
                            }}
                            onClick={(e) => {
                                e.stopPropagation()
                            }}
                        />
                    </div>
                )
            case 'timestamp':
                return (
                    <div key={column.key} style={cellStyle} className="flex items-center shrink-0">
                        <span className="text-xs text-muted font-mono">
                            <TZLabel time={log.timestamp} {...tzLabelFormat} timestampStyle="absolute" />
                        </span>
                    </div>
                )
            case 'message': {
                const isPrettyJson = prettifyJson && log.parsedBody
                const content = isPrettyJson ? JSON.stringify(log.parsedBody, null, 2) : log.cleanBody

                const scrollButtons = !wrapBody && (
                    <div
                        className="absolute right-0 top-0 bottom-0 flex items-center opacity-0 group-hover:opacity-100 transition-opacity bg-gradient-to-l from-bg-light via-bg-light to-transparent pl-4 pr-1"
                        onMouseDown={(e) => e.stopPropagation()}
                    >
                        <button
                            type="button"
                            title="Scroll left (← or h)"
                            aria-label="Scroll left"
                            className="p-1 text-muted hover:text-default cursor-pointer select-none"
                            onMouseDown={(e) => {
                                e.preventDefault()
                                startScrolling('left')
                            }}
                            onMouseUp={stopScrolling}
                            onMouseLeave={stopScrolling}
                        >
                            <IconChevronLeft className="text-lg" />
                        </button>
                        <button
                            type="button"
                            title="Scroll right (→ or l)"
                            aria-label="Scroll right"
                            className="p-1 text-muted hover:text-default cursor-pointer select-none"
                            onMouseDown={(e) => {
                                e.preventDefault()
                                startScrolling('right')
                            }}
                            onMouseUp={stopScrolling}
                            onMouseLeave={stopScrolling}
                        >
                            <IconChevronRight className="text-lg" />
                        </button>
                    </div>
                )

                if (isPrettyJson) {
                    return (
                        <div key={column.key} style={cellStyle} className="relative flex items-start py-1.5">
                            <div
                                ref={wrapBody ? undefined : messageScrollRef}
                                className={cn(
                                    'flex-1',
                                    wrapBody ? 'overflow-hidden' : 'overflow-x-auto hide-scrollbar'
                                )}
                                onScroll={wrapBody ? undefined : handleMessageScroll}
                            >
                                <pre
                                    className={cn(
                                        'font-mono text-xs m-0',
                                        wrapBody
                                            ? 'overflow-hidden whitespace-pre-wrap break-all'
                                            : 'whitespace-nowrap pr-16'
                                    )}
                                >
                                    {content}
                                </pre>
                            </div>
                            {scrollButtons}
                        </div>
                    )
                }

                return (
                    <div key={column.key} style={cellStyle} className="relative flex items-start py-1.5">
                        <div
                            ref={wrapBody ? undefined : messageScrollRef}
                            className={cn('flex-1', wrapBody ? 'overflow-hidden' : 'overflow-x-auto hide-scrollbar')}
                            onScroll={wrapBody ? undefined : handleMessageScroll}
                        >
                            <span
                                className={cn(
                                    'font-mono text-xs',
                                    wrapBody ? 'whitespace-pre-wrap break-all' : 'whitespace-nowrap pr-16'
                                )}
                            >
                                {content}
                            </span>
                        </div>
                        {scrollButtons}
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
                            onMouseDown={(e) => {
                                e.stopPropagation()
                                onTogglePin(log)
                            }}
                            onClick={(e) => {
                                e.stopPropagation()
                            }}
                            tooltip={pinned ? 'Unpin log' : 'Pin log'}
                            className={cn(pinned ? 'text-warning' : 'text-muted opacity-0 group-hover:opacity-100')}
                        />
                        <div className="opacity-0 group-hover:opacity-100" onMouseDown={(e) => e.stopPropagation()}>
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
                onMouseDown={onSetCursor}
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
            className="flex items-center h-8 border-b border-border bg-bg-3000 text-xs font-semibold text-muted sticky top-0 z-10"
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
