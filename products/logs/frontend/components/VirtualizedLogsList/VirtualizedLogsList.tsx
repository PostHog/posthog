import './VirtualizedLogsList.scss'

import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { List, ListRowProps } from 'react-virtualized/dist/es/List'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { TZLabelProps } from 'lib/components/TZLabel'
import { DetectiveHog } from 'lib/components/hedgehogs'

import { logDetailsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/logDetailsModalLogic'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { LogRow } from 'products/logs/frontend/components/VirtualizedLogsList/LogRow'
import { LogRowHeader } from 'products/logs/frontend/components/VirtualizedLogsList/LogRowHeader'
import {
    LOG_ROW_HEADER_HEIGHT,
    RESIZER_HANDLE_WIDTH,
    getMinRowWidth,
} from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

interface VirtualizedLogsListProps {
    dataSource: ParsedLogMessage[]
    loading: boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime' | 'displayTimezone'>
    showPinnedWithOpacity?: boolean
    disableCursor?: boolean
    fixedHeight?: number
    disableInfiniteScroll?: boolean
    hasMoreLogsToLoad?: boolean
    onLoadMore?: () => void
    onExpandTimeRange?: () => void
    orderBy?: LogsOrderBy
    onChangeOrderBy?: (orderBy: LogsOrderBy) => void
}

export function VirtualizedLogsList({
    dataSource,
    loading,
    wrapBody,
    prettifyJson,
    tzLabelFormat,
    showPinnedWithOpacity = false,
    disableCursor = false,
    fixedHeight,
    disableInfiniteScroll = false,
    hasMoreLogsToLoad = false,
    onLoadMore,
    onExpandTimeRange,
    orderBy,
    onChangeOrderBy,
}: VirtualizedLogsListProps): JSX.Element {
    const {
        tabId,
        pinnedLogs,
        expandedLogIds,
        cursorIndex,
        recomputeRowHeightsRequest,
        scrollToCursorRequest,
        attributeColumns,
        attributeColumnWidths,
        selectedLogIds,
        selectedCount,
        prettifiedLogIds,
        linkToLogId,
        logsCount,
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
        setFocused,
        setCursorToLogId,
    } = useActions(logsViewerLogic)
    const { openLogDetails } = useActions(logDetailsModalLogic)

    const containerRef = useRef<HTMLDivElement>(null)

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

    // Position cursor at linked log when deep linking (URL -> cursor)
    useEffect(() => {
        if (!disableCursor && linkToLogId && logsCount > 0) {
            setCursorToLogId(linkToLogId)
            containerRef.current?.focus()
            containerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
    }, [disableCursor, linkToLogId, logsCount, setCursorToLogId])

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

    // Scroll to cursor when requested (subscription fires when cursorIndex changes)
    useEffect(() => {
        if (!disableCursor && cursorIndex !== null) {
            listRef.current?.scrollToRow(cursorIndex)
            const raf = requestAnimationFrame(() => {
                listRef.current?.scrollToRow(cursorIndex)
            })
            return () => cancelAnimationFrame(raf)
        }
    }, [disableCursor, scrollToCursorRequest, cursorIndex])

    const handleRowsRendered = ({ stopIndex }: { stopIndex: number }): void => {
        if (!disableInfiniteScroll && shouldLoadMore(stopIndex, dataSource.length, hasMoreLogsToLoad, loading)) {
            onLoadMore?.()
        }
    }

    const handleLogRowClick = useCallback(
        (log: ParsedLogMessage, index: number): void => {
            openLogDetails(log)
            if (!disableCursor) {
                userSetCursorIndex(index)
            }
        },
        [disableCursor, openLogDetails, userSetCursorIndex]
    )

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
                                    logIndex={index}
                                    isAtCursor={!disableCursor && index === cursorIndex}
                                    isExpanded={!!expandedLogIds[log.uuid]}
                                    pinned={!!pinnedLogs[log.uuid]}
                                    showPinnedWithOpacity={showPinnedWithOpacity}
                                    wrapBody={wrapBody}
                                    prettifyJson={prettifyJson}
                                    tzLabelFormat={tzLabelFormat}
                                    onTogglePin={togglePinLog}
                                    onToggleExpand={() => toggleExpandLog(log.uuid)}
                                    onClick={() => handleLogRowClick(log, index)}
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
            disableCursor,
            wrapBody,
            prettifyJson,
            tzLabelFormat,
            togglePinLog,
            toggleExpandLog,
            openLogDetails,
            userSetCursorIndex,
            attributeColumns,
            attributeColumnWidths,
            selectedLogIds,
            toggleSelectLog,
            selectLogRange,
            prettifiedLogIds,
            togglePrettifyLog,
            handleLogRowClick,
        ]
    )

    if (dataSource.length === 0 && !loading) {
        return (
            <div className="flex flex-col items-center gap-3 p-8 text-center h-full min-h-40">
                <DetectiveHog className="w-32 h-32" />
                <div>
                    <h4 className="font-semibold m-0">No logs found</h4>
                    <p className="text-muted text-sm mt-1 mb-0 max-w-80">
                        Try adjusting your filters, expanding the time range, or checking that your app is sending logs.
                    </p>
                    <Link to="https://posthog.com/docs/logs/" target="_blank">
                        View documentation
                    </Link>
                </div>
                {onExpandTimeRange && (
                    <LemonButton type="secondary" size="small" onClick={onExpandTimeRange}>
                        Expand time range
                    </LemonButton>
                )}
            </div>
        )
    }

    // Fixed height mode for pinned logs
    if (fixedHeight !== undefined) {
        return (
            <div style={{ height: fixedHeight }} className="flex flex-col bg-bg-light border rounded overflow-hidden">
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
                                    orderBy={orderBy}
                                    onChangeOrderBy={onChangeOrderBy}
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
        <div
            tabIndex={0}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            ref={containerRef}
            className="gap-2 min-h-0 outline-none focus:ring-1 focus:ring-border-bold focus:ring-offset-1 h-full flex-1 flex flex-col bg-bg-light border rounded overflow-hidden"
            data-attr="logs-table"
        >
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
                                orderBy={orderBy}
                                onChangeOrderBy={onChangeOrderBy}
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
