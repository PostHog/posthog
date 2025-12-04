import './VirtualizedLogsList.scss'

import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { List, ListRowProps } from 'react-virtualized/dist/es/List'

import { TZLabelProps } from 'lib/components/TZLabel'

import {
    LOG_ROW_HEADER_HEIGHT,
    LogRow,
    LogRowHeader,
    getMinRowWidth,
} from 'products/logs/frontend/components/VirtualizedLogsList/LogRow'
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
    const { shouldLoadMore, containerWidth } = useValues(virtualizedLogsListLogic)
    const { setContainerWidth } = useActions(virtualizedLogsListLogic)
    const listRef = useRef<List>(null)
    const scrollTopRef = useRef<number>(0)
    const prevDataLengthRef = useRef<number>(0)
    const autosizerWidthRef = useRef<number>(0)

    const minRowWidth = useMemo(() => getMinRowWidth(), [])

    const cache = useMemo(
        () =>
            new CellMeasurerCache({
                fixedWidth: true,
                defaultHeight: 32,
                minHeight: 32,
            }),
        []
    )

    // Clear cache when container width changes (affects message column width and thus row heights)
    useEffect(() => {
        if (containerWidth > 0) {
            cache.clearAll()
            listRef.current?.recomputeRowHeights()
        }
    }, [containerWidth, cache])

    // Preserve scroll position when new data is appended
    useEffect(() => {
        if (dataSource.length > prevDataLengthRef.current && prevDataLengthRef.current > 0) {
            requestAnimationFrame(() => {
                listRef.current?.scrollToPosition(scrollTopRef.current)
            })
        }
        prevDataLengthRef.current = dataSource.length
    }, [dataSource.length])

    // Clear cache when display options change or when a fresh query starts
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

    useEffect(() => {
        if (highlightedLogId && highlightedLogId !== prevHighlightedLogIdRef.current) {
            requestAnimationFrame(() => {
                const index = dataSource.findIndex((log) => log.uuid === highlightedLogId)
                if (index !== -1) {
                    listRef.current?.scrollToRow(index)
                }
            })
        }
        prevHighlightedLogIdRef.current = highlightedLogId
    }, [highlightedLogId, dataSource])

    const handleRowsRendered = ({ stopIndex }: { stopIndex: number }): void => {
        if (disableInfiniteScroll) {
            return
        }
        if (shouldLoadMore(stopIndex, dataSource.length, hasMoreLogsToLoad, logsLoading)) {
            fetchNextLogsPage(250)
        }
    }

    const createRowRenderer = useCallback(
        (rowWidth?: number) =>
            ({ index, key, style, parent }: ListRowProps): JSX.Element => {
                const log = dataSource[index]
                const isHighlighted = log.uuid === highlightedLogId
                const pinned = isPinned(log.uuid)

                return (
                    <CellMeasurer cache={cache} columnIndex={0} key={key} parent={parent} rowIndex={index}>
                        {({ registerChild }) => (
                            <div
                                ref={registerChild as React.LegacyRef<HTMLDivElement>}
                                style={style}
                                data-row-key={log.uuid}
                            >
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
                                    rowWidth={rowWidth}
                                />
                            </div>
                        )}
                    </CellMeasurer>
                )
            },
        [
            dataSource,
            highlightedLogId,
            isPinned,
            cache,
            showPinnedWithOpacity,
            wrapBody,
            prettifyJson,
            tzLabelFormat,
            togglePinLog,
            setHighlightedLogId,
        ]
    )

    if (dataSource.length === 0 && !loading) {
        return <div className="p-4 text-muted text-center">No logs to display</div>
    }

    // Fixed height mode for pinned logs
    if (fixedHeight !== undefined) {
        return (
            <div style={{ height: fixedHeight }} className="flex flex-col">
                <AutoSizer disableHeight>
                    {({ width }) => {
                        if (width !== autosizerWidthRef.current) {
                            autosizerWidthRef.current = width
                            requestAnimationFrame(() => setContainerWidth(width))
                        }
                        const rowWidth = Math.max(width, minRowWidth)
                        return (
                            <div className="overflow-x-auto" style={{ width, height: fixedHeight }}>
                                <LogRowHeader rowWidth={rowWidth} />
                                <List
                                    ref={listRef}
                                    width={rowWidth}
                                    height={fixedHeight - LOG_ROW_HEADER_HEIGHT}
                                    rowCount={dataSource.length}
                                    rowHeight={cache.rowHeight}
                                    deferredMeasurementCache={cache}
                                    rowRenderer={createRowRenderer(rowWidth)}
                                    overscanRowCount={5}
                                    tabIndex={null}
                                    style={{ outline: 'none', overflowX: 'hidden' }}
                                />
                            </div>
                        )
                    }}
                </AutoSizer>
            </div>
        )
    }

    return (
        <div className="h-full flex-1 flex flex-col">
            <AutoSizer>
                {({ width, height }) => {
                    if (width !== autosizerWidthRef.current) {
                        autosizerWidthRef.current = width
                        requestAnimationFrame(() => setContainerWidth(width))
                    }
                    const rowWidth = Math.max(width, minRowWidth)

                    return (
                        <div className="overflow-x-auto" style={{ width, height }}>
                            <LogRowHeader rowWidth={rowWidth} />
                            <List
                                ref={listRef}
                                width={rowWidth}
                                height={height - LOG_ROW_HEADER_HEIGHT}
                                rowCount={dataSource.length}
                                rowHeight={cache.rowHeight}
                                deferredMeasurementCache={cache}
                                rowRenderer={createRowRenderer(rowWidth)}
                                onRowsRendered={handleRowsRendered}
                                onScroll={({ scrollTop }) => {
                                    scrollTopRef.current = scrollTop
                                }}
                                overscanRowCount={10}
                                tabIndex={null}
                                style={{ outline: 'none', overflowX: 'hidden' }}
                            />
                        </div>
                    )
                }}
            </AutoSizer>
        </div>
    )
}
