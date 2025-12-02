import './VirtualizedLogsList.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { List, ListRowProps } from 'react-virtualized/dist/es/List'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import { LogTag } from 'products/logs/frontend/components/LogTag'
import { LogsTableRowActions } from 'products/logs/frontend/components/LogsTable/LogsTableRowActions'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { logsLogic } from 'products/logs/frontend/logsLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'

const SEVERITY_BAR_COLORS: Record<LogMessage['severity_text'], string> = {
    trace: 'bg-muted-alt',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-danger',
    fatal: 'bg-danger-dark',
}

interface VirtualizedLogsListProps {
    dataSource: ParsedLogMessage[]
    loading: boolean
    isPinned: (uuid: string) => boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'>
    showPinnedWithOpacity?: boolean
    fixedHeight?: number
    disableInfiniteScroll?: boolean
}

export function VirtualizedLogsList({
    dataSource,
    loading,
    isPinned,
    wrapBody,
    prettifyJson,
    tzLabelFormat,
    showPinnedWithOpacity = false,
    fixedHeight,
    disableInfiniteScroll = false,
}: VirtualizedLogsListProps): JSX.Element {
    const { togglePinLog, setHighlightedLogId, fetchNextLogsPage } = useActions(logsLogic)
    const { highlightedLogId, hasMoreLogsToLoad, logsLoading } = useValues(logsLogic)
    const { shouldLoadMore } = useValues(virtualizedLogsListLogic)
    const listRef = useRef<List>(null)
    const scrollTopRef = useRef<number>(0)
    const prevDataLengthRef = useRef<number>(0)

    // Preserve scroll position when new data is appended
    useEffect(() => {
        if (dataSource.length > prevDataLengthRef.current && prevDataLengthRef.current > 0) {
            // Data was appended, restore scroll position
            requestAnimationFrame(() => {
                listRef.current?.scrollToPosition(scrollTopRef.current)
            })
        }
        prevDataLengthRef.current = dataSource.length
    }, [dataSource.length])

    const cache = useMemo(
        () =>
            new CellMeasurerCache({
                fixedWidth: true,
                defaultHeight: 32,
                minHeight: 32,
            }),
        []
    )

    // Clear cache when display options change or when a fresh query starts (loading + empty data)
    useEffect(() => {
        if (logsLoading && dataSource.length === 0) {
            cache.clearAll()
        }
    }, [logsLoading, dataSource.length, cache])

    useEffect(() => {
        cache.clearAll()
        listRef.current?.recomputeRowHeights()
    }, [wrapBody, prettifyJson, cache])

    const prevHighlightedLogIdRef = useRef<string | null>(null)

    // Only scroll to highlighted log when it changes, not on every data update
    useEffect(() => {
        if (highlightedLogId && highlightedLogId !== prevHighlightedLogIdRef.current && listRef.current) {
            requestAnimationFrame(() => {
                const index = dataSource.findIndex((log) => log.uuid === highlightedLogId)
                if (index !== -1) {
                    listRef.current?.scrollToRow(index)
                }
            })
        }
        prevHighlightedLogIdRef.current = highlightedLogId
    }, [highlightedLogId, dataSource])

    const rowRenderer = ({ index, key, style, parent }: ListRowProps): JSX.Element => {
        const log = dataSource[index]
        const isHighlighted = log.uuid === highlightedLogId
        const pinned = isPinned(log.uuid)
        const isNew = 'new' in log && log.new

        return (
            <CellMeasurer cache={cache} columnIndex={0} key={key} parent={parent} rowIndex={index}>
                {({ registerChild }) => (
                    <div ref={registerChild as React.LegacyRef<HTMLDivElement>} style={style} data-row-key={log.uuid}>
                        {/* Inner div with unique key when "new" to force animation restart on recycled DOM nodes */}
                        <div
                            key={isNew ? `new-${log.uuid}` : log.uuid}
                            className={cn(
                                'flex items-center gap-3 px-2 py-1.5 border-b border-border cursor-pointer hover:bg-fill-highlight-100 group',
                                isHighlighted && 'bg-primary-highlight',
                                pinned && 'bg-warning-highlight',
                                pinned && showPinnedWithOpacity && 'opacity-50',
                                isNew && 'VirtualizedLogsList__row--new'
                            )}
                            onClick={() => setHighlightedLogId(isHighlighted ? null : log.uuid)}
                        >
                            <div
                                className={cn(
                                    'w-1 self-stretch rounded-full shrink-0',
                                    SEVERITY_BAR_COLORS[log.severity_text] ?? 'bg-muted-3000'
                                )}
                            />
                            <span
                                className={cn(
                                    'w-8 text-xs shrink-0 font-mono tabular-nums opacity-40',
                                    isHighlighted ? 'text-primary font-semibold' : 'text-muted'
                                )}
                            >
                                {index + 1}
                            </span>
                            <span className="w-[180px] text-xs text-muted shrink-0 font-mono">
                                <TZLabel time={log.timestamp} {...tzLabelFormat} showNow={false} showToday={false} />
                            </span>
                            <span className="shrink-0">
                                <LogTag level={log.severity_text} />
                            </span>
                            <span
                                className={cn(
                                    'flex-1 font-mono text-xs break-all',
                                    wrapBody || (prettifyJson && log.parsedBody) ? 'whitespace-pre-wrap' : 'truncate'
                                )}
                            >
                                {log.parsedBody && prettifyJson
                                    ? JSON.stringify(log.parsedBody, null, 2)
                                    : log.cleanBody}
                            </span>
                            <div className="flex items-center gap-1 shrink-0">
                                <LemonButton
                                    size="xsmall"
                                    noPadding
                                    icon={pinned ? <IconPinFilled /> : <IconPin />}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        togglePinLog(log.uuid)
                                    }}
                                    tooltip={pinned ? 'Unpin log' : 'Pin log'}
                                    className={cn(
                                        pinned ? 'text-warning' : 'text-muted opacity-0 group-hover:opacity-100'
                                    )}
                                />
                                <div className="opacity-0 group-hover:opacity-100" onClick={(e) => e.stopPropagation()}>
                                    <LogsTableRowActions log={log} />
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </CellMeasurer>
        )
    }

    const handleRowsRendered = ({ stopIndex }: { stopIndex: number }): void => {
        if (disableInfiniteScroll) {
            return
        }
        if (shouldLoadMore(stopIndex, dataSource.length, hasMoreLogsToLoad, logsLoading)) {
            fetchNextLogsPage(250)
        }
    }

    if (dataSource.length === 0 && !loading) {
        return <div className="p-4 text-muted text-center">No logs to display</div>
    }

    // Fixed height mode for pinned logs
    if (fixedHeight !== undefined) {
        return (
            <div style={{ height: fixedHeight }}>
                <AutoSizer disableHeight>
                    {({ width }) => (
                        <List
                            ref={listRef}
                            width={width}
                            height={fixedHeight}
                            rowCount={dataSource.length}
                            rowHeight={cache.rowHeight}
                            deferredMeasurementCache={cache}
                            rowRenderer={rowRenderer}
                            overscanRowCount={5}
                            tabIndex={null}
                            style={{ outline: 'none' }}
                        />
                    )}
                </AutoSizer>
            </div>
        )
    }

    return (
        <div className="h-full flex-1">
            <AutoSizer>
                {({ width, height }) => (
                    <List
                        ref={listRef}
                        width={width}
                        height={height}
                        rowCount={dataSource.length}
                        rowHeight={cache.rowHeight}
                        deferredMeasurementCache={cache}
                        rowRenderer={rowRenderer}
                        overscanRowCount={10}
                        onRowsRendered={handleRowsRendered}
                        onScroll={({ scrollTop }) => {
                            scrollTopRef.current = scrollTop
                        }}
                        tabIndex={null}
                        style={{ outline: 'none' }}
                    />
                )}
            </AutoSizer>
        </div>
    )
}
