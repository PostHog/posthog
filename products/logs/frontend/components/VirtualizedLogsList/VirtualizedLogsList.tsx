import './VirtualizedLogsList.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { List, ListRowProps } from 'react-virtualized/dist/es/List'

import { TZLabelProps } from 'lib/components/TZLabel'

import { LogRow } from 'products/logs/frontend/components/VirtualizedLogsList/LogRow'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { logsLogic } from 'products/logs/frontend/logsLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'

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

        return (
            <CellMeasurer cache={cache} columnIndex={0} key={key} parent={parent} rowIndex={index}>
                {({ registerChild }) => (
                    <div ref={registerChild as React.LegacyRef<HTMLDivElement>} style={style} data-row-key={log.uuid}>
                        <LogRow
                            log={log}
                            isHighlighted={isHighlighted}
                            pinned={pinned}
                            showPinnedWithOpacity={showPinnedWithOpacity}
                            wrapBody={wrapBody}
                            prettifyJson={prettifyJson}
                            tzLabelFormat={tzLabelFormat}
                            onTogglePin={togglePinLog}
                            onSetHighlighted={setHighlightedLogId}
                        />
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
