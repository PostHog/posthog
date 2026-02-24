import './VirtualizedLogsList.scss'

import { useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useEffect, useMemo, useRef } from 'react'
import { List, getScrollbarSize, useDynamicRowHeight, useListRef } from 'react-window'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { DetectiveHog } from 'lib/components/hedgehogs'
import { TZLabelProps } from 'lib/components/TZLabel'
import { useViewportVirtualization } from 'lib/lemon-ui/LemonTable/useViewportVirtualization'

import { logDetailsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/logDetailsModalLogic'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import {
    LOG_ROW_HEADER_HEIGHT,
    RESIZER_HANDLE_WIDTH,
    getMinRowWidth,
} from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { LogRow } from 'products/logs/frontend/components/VirtualizedLogsList/LogRow'
import { LogRowHeader } from 'products/logs/frontend/components/VirtualizedLogsList/LogRowHeader'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

const DEFAULT_ROW_HEIGHT = 32

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

interface LogsListRowProps {
    dataSource: ParsedLogMessage[]
    cursorIndex: number | null
    expandedLogIds: Record<string, boolean>
    pinnedLogs: Record<string, ParsedLogMessage>
    showPinnedWithOpacity: boolean
    disableCursor: boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime' | 'displayTimezone'>
    togglePinLog: (log: ParsedLogMessage) => void
    toggleExpandLog: (logId: string) => void
    handleLogRowClick: (log: ParsedLogMessage, index: number) => void
    rowWidth?: number
    attributeColumns: string[]
    attributeColumnWidths: Record<string, number>
    selectedLogIds: Record<string, boolean>
    toggleSelectLog: (logId: string) => void
    selectLogRange: (anchorIndex: number, clickedIndex: number) => void
    userSetCursorIndex: (index: number) => void
    prettifiedLogIds: Set<string>
    togglePrettifyLog: (logId: string) => void
    dynamicRowHeight: ReturnType<typeof useDynamicRowHeight>
}

function LogsListRow({
    index,
    style,
    dataSource,
    cursorIndex,
    expandedLogIds,
    pinnedLogs,
    showPinnedWithOpacity,
    disableCursor,
    wrapBody,
    prettifyJson,
    tzLabelFormat,
    togglePinLog,
    toggleExpandLog,
    handleLogRowClick,
    rowWidth,
    attributeColumns,
    attributeColumnWidths,
    selectedLogIds,
    toggleSelectLog,
    selectLogRange,
    userSetCursorIndex,
    prettifiedLogIds,
    togglePrettifyLog,
    dynamicRowHeight,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & LogsListRowProps): JSX.Element {
    const rowRef = useRef<HTMLDivElement>(null)
    const log = dataSource[index]

    useEffect(() => {
        if (rowRef.current) {
            return dynamicRowHeight.observeRowElements([rowRef.current])
        }
    }, [dynamicRowHeight])

    return (
        <div ref={rowRef} style={style} data-index={index} data-row-key={log.uuid}>
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
    )
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
        id,
        pinnedLogs,
        expandedLogIds,
        cursorIndex,
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

    const { shouldLoadMore } = useValues(virtualizedLogsListLogic({ id }))
    const { setContainerWidth } = useActions(virtualizedLogsListLogic({ id }))
    const listRef = useListRef(null)
    const autosizerWidthRef = useRef<number>(0)

    const dynamicRowHeight = useDynamicRowHeight({ defaultRowHeight: DEFAULT_ROW_HEIGHT })

    const minRowWidth = useMemo(
        () => getMinRowWidth(attributeColumns, attributeColumnWidths) + attributeColumns.length * RESIZER_HANDLE_WIDTH,
        [attributeColumns, attributeColumnWidths]
    )

    // Position cursor at linked log when deep linking (URL -> cursor)
    useEffect(() => {
        if (!disableCursor && linkToLogId && logsCount > 0) {
            setCursorToLogId(linkToLogId)
            containerRef.current?.focus()
            containerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
    }, [disableCursor, linkToLogId, logsCount, setCursorToLogId])

    // Scroll to cursor when requested — for fixed-height mode use react-window, for viewport mode use scrollIntoView
    useEffect(() => {
        if (!disableCursor && cursorIndex !== null && cursorIndex >= 0) {
            if (fixedHeight !== undefined) {
                listRef.current?.scrollToRow({ index: cursorIndex })
                const raf = requestAnimationFrame(() => {
                    listRef.current?.scrollToRow({ index: cursorIndex })
                })
                return () => cancelAnimationFrame(raf)
            }
            // Viewport mode: find the row element by data-index and scroll it into view
            const rowEl = containerRef.current?.querySelector(`[data-index="${cursorIndex}"]`)
            if (rowEl) {
                rowEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
            }
        }
    }, [disableCursor, scrollToCursorRequest, cursorIndex, listRef, fixedHeight])

    const handleLogRowClick = useCallback(
        (log: ParsedLogMessage, index: number): void => {
            openLogDetails(log)
            if (!disableCursor) {
                userSetCursorIndex(index)
            }
        },
        [disableCursor, openLogDetails, userSetCursorIndex]
    )

    const createRowProps = useCallback(
        (rowWidth?: number): LogsListRowProps => ({
            dataSource,
            cursorIndex,
            expandedLogIds,
            pinnedLogs,
            showPinnedWithOpacity,
            disableCursor,
            wrapBody,
            prettifyJson,
            tzLabelFormat,
            togglePinLog,
            toggleExpandLog,
            handleLogRowClick,
            rowWidth,
            attributeColumns,
            attributeColumnWidths,
            selectedLogIds,
            toggleSelectLog,
            selectLogRange,
            userSetCursorIndex,
            prettifiedLogIds,
            togglePrettifyLog,
            dynamicRowHeight,
        }),
        [
            dataSource,
            cursorIndex,
            expandedLogIds,
            pinnedLogs,
            showPinnedWithOpacity,
            disableCursor,
            wrapBody,
            prettifyJson,
            tzLabelFormat,
            togglePinLog,
            toggleExpandLog,
            handleLogRowClick,
            attributeColumns,
            attributeColumnWidths,
            selectedLogIds,
            toggleSelectLog,
            selectLogRange,
            userSetCursorIndex,
            prettifiedLogIds,
            togglePrettifyLog,
            dynamicRowHeight,
        ]
    )

    // Viewport-based virtualization for the main logs list
    const { startIndex, endIndex, topSpacerHeight, bottomSpacerHeight } = useViewportVirtualization(containerRef, {
        rowCount: dataSource.length,
        estimatedRowHeight: DEFAULT_ROW_HEIGHT,
        overscan: 20,
        enabled: fixedHeight === undefined,
    })

    // Infinite scroll: trigger load more when the visible range approaches the end
    useEffect(() => {
        if (
            fixedHeight === undefined &&
            !disableInfiniteScroll &&
            shouldLoadMore(endIndex, dataSource.length, hasMoreLogsToLoad, loading)
        ) {
            onLoadMore?.()
        }
    }, [
        endIndex,
        disableInfiniteScroll,
        shouldLoadMore,
        dataSource.length,
        hasMoreLogsToLoad,
        loading,
        onLoadMore,
        fixedHeight,
    ])

    // Measure container width via ResizeObserver for viewport mode
    useEffect(() => {
        if (fixedHeight !== undefined || !containerRef.current) {
            return
        }
        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const width = entry.contentRect.width
                if (width && width !== autosizerWidthRef.current) {
                    autosizerWidthRef.current = width
                    requestAnimationFrame(() => setContainerWidth(width))
                }
            }
        })
        observer.observe(containerRef.current)
        return () => observer.disconnect()
    }, [fixedHeight, setContainerWidth])

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

    // Fixed height mode for pinned logs — keeps using react-window for contained scrolling
    if (fixedHeight !== undefined) {
        return (
            <div style={{ height: fixedHeight }} className="flex flex-col bg-bg-light border rounded overflow-hidden">
                <AutoSizer
                    disableHeight
                    renderProp={({ width }: SizeProps) => {
                        if (width && width !== autosizerWidthRef.current) {
                            autosizerWidthRef.current = width
                            requestAnimationFrame(() => setContainerWidth(width))
                        }
                        const rowWidth = Math.max(width ?? 0, minRowWidth)
                        return (
                            <div className="overflow-y-hidden overflow-x-auto" style={{ width, height: fixedHeight }}>
                                <LogRowHeader
                                    rowWidth={rowWidth - getScrollbarSize()}
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
                                <List<LogsListRowProps>
                                    style={{ height: fixedHeight - LOG_ROW_HEADER_HEIGHT, width: rowWidth }}
                                    overscanCount={5}
                                    rowCount={dataSource.length}
                                    rowHeight={dynamicRowHeight}
                                    rowComponent={LogsListRow}
                                    rowProps={createRowProps(rowWidth - getScrollbarSize())}
                                    listRef={listRef}
                                />
                            </div>
                        )
                    }}
                />
            </div>
        )
    }

    // Viewport-virtualized mode: the list flows naturally in the page, no inner scroll container
    const containerWidth = autosizerWidthRef.current || undefined
    const rowWidth = Math.max(containerWidth ?? 0, minRowWidth)

    return (
        <div
            tabIndex={0}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            ref={containerRef}
            className="min-h-0 outline-none focus:ring-1 focus:ring-border-bold focus:ring-offset-1 flex flex-col bg-bg-light border rounded"
            data-attr="logs-table"
        >
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
            {topSpacerHeight > 0 && <div aria-hidden="true" style={{ height: topSpacerHeight, flexShrink: 0 }} />}
            {dataSource.slice(startIndex, endIndex).map((log, sliceIndex) => {
                const index = startIndex + sliceIndex
                return (
                    <div key={log.uuid} data-index={index} data-row-key={log.uuid}>
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
                )
            })}
            {bottomSpacerHeight > 0 && <div aria-hidden="true" style={{ height: bottomSpacerHeight, flexShrink: 0 }} />}
            {loading && dataSource.length > 0 && (
                <div className="flex items-center justify-center py-2 text-muted text-sm">Loading more logs...</div>
            )}
        </div>
    )
}
