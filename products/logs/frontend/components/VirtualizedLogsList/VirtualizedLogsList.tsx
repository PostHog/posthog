import './VirtualizedLogsList.scss'

import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { List, ListRowProps } from 'react-virtualized/dist/es/List'

import { TZLabelProps } from 'lib/components/TZLabel'

import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import {
    LOG_ROW_HEADER_HEIGHT,
    LogRow,
    LogRowHeader,
    getMinRowWidth,
} from 'products/logs/frontend/components/VirtualizedLogsList/LogRow'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'

interface VirtualizedLogsListProps {
    dataSource: ParsedLogMessage[]
    loading: boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'>
    showPinnedWithOpacity?: boolean
    fixedHeight?: number
    disableInfiniteScroll?: boolean
    hasMoreLogsToLoad?: boolean
    onLoadMore?: () => void
}

export function VirtualizedLogsList({
    dataSource,
    loading,
    wrapBody,
    prettifyJson,
    tzLabelFormat,
    showPinnedWithOpacity = false,
    fixedHeight,
    disableInfiniteScroll = false,
    hasMoreLogsToLoad = false,
    onLoadMore,
}: VirtualizedLogsListProps): JSX.Element {
    const { togglePinLog, userSetCursorIndex } = useActions(logsViewerLogic)
    const { pinnedLogs, cursorIndex } = useValues(logsViewerLogic)
    const { shouldLoadMore, containerWidth } = useValues(virtualizedLogsListLogic)
    const { setContainerWidth } = useActions(virtualizedLogsListLogic)
    const listRef = useRef<List>(null)
    const scrollTopRef = useRef<number>(0)
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
    }, [containerWidth, cache, wrapBody, prettifyJson])

    // Clear cache when display options change or when a fresh query starts
    useEffect(() => {
        if (loading && dataSource.length === 0) {
            cache.clearAll()
        }
    }, [loading, dataSource.length, cache])

    useEffect(() => {
        if (cursorIndex !== null && dataSource.length > 0) {
            listRef.current?.scrollToRow(cursorIndex)
            // Double scroll after two animation frames to ensure row measurement is complete
            let raf1: number | null = null
            let raf2: number | null = null
            raf1 = requestAnimationFrame(() => {
                raf2 = requestAnimationFrame(() => {
                    listRef.current?.scrollToRow(cursorIndex)
                })
            })
            return () => {
                if (raf1 !== null) {
                    cancelAnimationFrame(raf1)
                }
                if (raf2 !== null) {
                    cancelAnimationFrame(raf2)
                }
            }
        }
    }, [cursorIndex, dataSource.length])

    const handleRowsRendered = ({ stopIndex }: { stopIndex: number }): void => {
        if (disableInfiniteScroll) {
            return
        }
        if (shouldLoadMore(stopIndex, dataSource.length, hasMoreLogsToLoad, loading)) {
            onLoadMore?.()
        }
    }

    const createRowRenderer = useCallback(
        (rowWidth?: number) =>
            ({ index, key, style, parent }: ListRowProps): JSX.Element => {
                const log = dataSource[index]

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
                                    isAtCursor={index === cursorIndex}
                                    pinned={!!pinnedLogs[log.uuid]}
                                    showPinnedWithOpacity={showPinnedWithOpacity}
                                    wrapBody={wrapBody}
                                    prettifyJson={prettifyJson}
                                    tzLabelFormat={tzLabelFormat}
                                    onTogglePin={togglePinLog}
                                    onSetCursor={() => userSetCursorIndex(index)}
                                    rowWidth={rowWidth}
                                />
                            </div>
                        )}
                    </CellMeasurer>
                )
            },
        [
            dataSource,
            cursorIndex,
            pinnedLogs,
            cache,
            showPinnedWithOpacity,
            wrapBody,
            prettifyJson,
            tzLabelFormat,
            togglePinLog,
            userSetCursorIndex,
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
