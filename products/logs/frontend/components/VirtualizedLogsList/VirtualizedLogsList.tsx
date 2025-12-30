import './VirtualizedLogsList.scss'

import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { List, ListRowProps } from 'react-virtualized/dist/es/List'

import { TZLabelProps } from 'lib/components/TZLabel'

import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { LogRow } from 'products/logs/frontend/components/VirtualizedLogsList/LogRow'
import { LogRowHeader } from 'products/logs/frontend/components/VirtualizedLogsList/LogRowHeader'
import {
    LOG_ROW_HEADER_HEIGHT,
    RESIZER_HANDLE_WIDTH,
    getMinRowWidth,
} from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { ParsedLogMessage } from 'products/logs/frontend/types'

interface VirtualizedLogsListProps {
    dataSource: ParsedLogMessage[]
    loading: boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime' | 'displayTimezone'>
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
    const {
        tabId,
        pinnedLogs,
        expandedLogIds,
        cursorIndex,
        recomputeRowHeightsRequest,
        attributeColumns,
        attributeColumnWidths,
        selectedLogIds,
        selectedCount,
        prettifiedLogIds,
    } = useValues(logsViewerLogic)
    const {
        togglePinLog,
        toggleExpandLog,
        userSetCursorIndex,
        removeAttributeColumn,
        setAttributeColumnWidth,
        moveAttributeColumn,
        toggleSelectLog,
        selectAll,
        clearSelection,
        selectLogRange,
        togglePrettifyLog,
    } = useActions(logsViewerLogic)

    const { shouldLoadMore, containerWidth } = useValues(virtualizedLogsListLogic({ tabId }))
    const { setContainerWidth } = useActions(virtualizedLogsListLogic({ tabId }))
    const listRef = useRef<List>(null)
    const scrollTopRef = useRef<number>(0)
    const autosizerWidthRef = useRef<number>(0)

    const minRowWidth = useMemo(
        // Add extra width for resize handles in the header
        () => getMinRowWidth(attributeColumns, attributeColumnWidths) + attributeColumns.length * RESIZER_HANDLE_WIDTH,
        [attributeColumns, attributeColumnWidths]
    )

    const cache = useMemo(
        () =>
            new CellMeasurerCache({
                fixedWidth: true,
                defaultHeight: 32,
                minHeight: 32,
            }),
        []
    )

    // Handle recompute requests from child components (via the logic)
    const lastRecomputeTimestampRef = useRef<number>(0)
    useEffect(() => {
        if (recomputeRowHeightsRequest && recomputeRowHeightsRequest.timestamp > lastRecomputeTimestampRef.current) {
            lastRecomputeTimestampRef.current = recomputeRowHeightsRequest.timestamp
            const { logIds } = recomputeRowHeightsRequest
            if (logIds) {
                for (const logId of logIds) {
                    const rowIndex = dataSource.findIndex((log) => log.uuid === logId)
                    if (rowIndex !== -1) {
                        cache.clear(rowIndex, 0)
                        listRef.current?.recomputeRowHeights(rowIndex)
                    }
                }
            } else {
                cache.clearAll()
                listRef.current?.recomputeRowHeights()
            }
        }
    }, [recomputeRowHeightsRequest, dataSource, cache])

    // Clear cache when container width changes (affects message column width and thus row heights)
    useEffect(() => {
        if (containerWidth > 0) {
            cache.clearAll()
            listRef.current?.recomputeRowHeights()
        }
    }, [containerWidth, cache, wrapBody, prettifyJson, attributeColumns, attributeColumnWidths])

    // Clear cache when display options change or when a fresh query starts
    useEffect(() => {
        if (loading && dataSource.length === 0) {
            cache.clearAll()
        }
    }, [loading, dataSource.length, cache])

    // Scroll to cursor when it changes (but not when data length changes from pagination)
    const prevCursorIndexRef = useRef<number | null>(cursorIndex)
    useEffect(() => {
        const cursorChanged = cursorIndex !== prevCursorIndexRef.current
        prevCursorIndexRef.current = cursorIndex

        if (cursorChanged && cursorIndex !== null && dataSource.length > 0) {
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
                const isExpanded = !!expandedLogIds[log.uuid]

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
                                    logIndex={index}
                                    isAtCursor={index === cursorIndex}
                                    isExpanded={isExpanded}
                                    pinned={!!pinnedLogs[log.uuid]}
                                    showPinnedWithOpacity={showPinnedWithOpacity}
                                    wrapBody={wrapBody}
                                    prettifyJson={prettifyJson}
                                    tzLabelFormat={tzLabelFormat}
                                    onTogglePin={togglePinLog}
                                    onToggleExpand={() => toggleExpandLog(log.uuid)}
                                    onSetCursor={() => userSetCursorIndex(index)}
                                    rowWidth={rowWidth}
                                    attributeColumns={attributeColumns}
                                    attributeColumnWidths={attributeColumnWidths}
                                    isSelected={!!selectedLogIds[log.uuid]}
                                    onToggleSelect={() => toggleSelectLog(log.uuid)}
                                    onShiftClick={(clickedIndex) => {
                                        const anchorIndex = cursorIndex ?? 0
                                        selectLogRange(anchorIndex, clickedIndex)
                                        userSetCursorIndex(clickedIndex)
                                    }}
                                    isPrettified={prettifiedLogIds.has(log.uuid)}
                                    onTogglePrettify={(l) => togglePrettifyLog(l.uuid)}
                                />
                            </div>
                        )}
                    </CellMeasurer>
                )
            },
        [
            dataSource,
            cursorIndex,
            expandedLogIds,
            pinnedLogs,
            cache,
            showPinnedWithOpacity,
            wrapBody,
            prettifyJson,
            tzLabelFormat,
            togglePinLog,
            toggleExpandLog,
            userSetCursorIndex,
            attributeColumns,
            attributeColumnWidths,
            selectedLogIds,
            toggleSelectLog,
            selectLogRange,
            prettifiedLogIds,
            togglePrettifyLog,
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
                            <div className="overflow-y-hidden overflow-x-auto" style={{ width, height: fixedHeight }}>
                                <LogRowHeader
                                    rowWidth={rowWidth}
                                    attributeColumns={attributeColumns}
                                    attributeColumnWidths={attributeColumnWidths}
                                    onRemoveAttributeColumn={removeAttributeColumn}
                                    onResizeAttributeColumn={setAttributeColumnWidth}
                                    onMoveAttributeColumn={moveAttributeColumn}
                                    selectedCount={selectedCount}
                                    totalCount={dataSource.length}
                                    onSelectAll={() => selectAll(dataSource)}
                                    onClearSelection={clearSelection}
                                />
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
                        <div className="overflow-y-hidden overflow-x-auto" style={{ width, height }}>
                            <LogRowHeader
                                rowWidth={rowWidth}
                                attributeColumns={attributeColumns}
                                attributeColumnWidths={attributeColumnWidths}
                                onRemoveAttributeColumn={removeAttributeColumn}
                                onResizeAttributeColumn={setAttributeColumnWidth}
                                onMoveAttributeColumn={moveAttributeColumn}
                                selectedCount={selectedCount}
                                totalCount={dataSource.length}
                                onSelectAll={() => selectAll(dataSource)}
                                onClearSelection={clearSelection}
                            />
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
