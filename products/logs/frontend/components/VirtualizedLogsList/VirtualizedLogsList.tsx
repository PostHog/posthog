import './VirtualizedLogsList.scss'

import { useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useEffect, useMemo, useRef } from 'react'
import { List, getScrollbarSize, useDynamicRowHeight, useListRef } from 'react-window'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { TZLabelProps } from 'lib/components/TZLabel'

import { isPinnedColumn } from 'products/logs/frontend/components/LogsViewer/config/columns'
import { logsViewerDataLogic } from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'
import { logDetailsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/logDetailsModalLogic'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import {
    createConfiguredColumn,
    createControlsColumn,
} from 'products/logs/frontend/components/VirtualizedLogsList/columnDefinitions'
import {
    LOG_ROW_HEADER_HEIGHT,
    getColumnsFixedWidth,
    getColumnsMinRowWidth,
} from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { LogRow } from 'products/logs/frontend/components/VirtualizedLogsList/LogRow'
import { LogRowHeader } from 'products/logs/frontend/components/VirtualizedLogsList/LogRowHeader'
import { VirtualizedTableColumn } from 'products/logs/frontend/components/VirtualizedLogsList/types'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

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
    /** Uuids of the latest live-tail batch — these rows play the one-shot arrival highlight. */
    newLogUuids?: Set<string>
}

interface LogsListRowProps {
    dataSource: ParsedLogMessage[]
    columns: VirtualizedTableColumn<ParsedLogMessage>[]
    cursorIndex: number | null
    expandedLogIds: Record<string, boolean>
    pinnedLogs: Record<string, ParsedLogMessage>
    showPinnedWithOpacity: boolean
    disableCursor: boolean
    wrapBody: boolean
    hasMessageColumn: boolean
    togglePinLog: (log: ParsedLogMessage) => void
    handleLogRowClick: (log: ParsedLogMessage, index: number) => void
    rowWidth?: number
    selectedLogIds: Record<string, boolean>
    selectLogRange: (anchorIndex: number, clickedIndex: number) => void
    userSetCursorIndex: (index: number) => void
    prettifiedLogIds: Set<string>
    togglePrettifyLog: (logId: string) => void
    dynamicRowHeight: ReturnType<typeof useDynamicRowHeight>
    newLogUuids?: Set<string>
}

function LogsListRow({
    index,
    style,
    dataSource,
    columns,
    cursorIndex,
    expandedLogIds,
    pinnedLogs,
    showPinnedWithOpacity,
    disableCursor,
    wrapBody,
    hasMessageColumn,
    togglePinLog,
    handleLogRowClick,
    rowWidth,
    selectedLogIds,
    selectLogRange,
    userSetCursorIndex,
    prettifiedLogIds,
    togglePrettifyLog,
    dynamicRowHeight,
    newLogUuids,
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
                columns={columns}
                isAtCursor={!disableCursor && index === cursorIndex}
                isExpanded={!!expandedLogIds[log.uuid]}
                pinned={!!pinnedLogs[log.uuid]}
                showPinnedWithOpacity={showPinnedWithOpacity}
                wrapBody={wrapBody}
                hasMessageColumn={hasMessageColumn}
                onTogglePin={togglePinLog}
                onClick={() => handleLogRowClick(log, index)}
                rowWidth={rowWidth}
                isSelected={!!selectedLogIds[log.uuid]}
                onShiftClick={(clickedIndex) => {
                    const anchorIndex = cursorIndex ?? 0
                    selectLogRange(anchorIndex, clickedIndex)
                    userSetCursorIndex(clickedIndex)
                }}
                isPrettified={prettifiedLogIds.has(log.uuid)}
                onTogglePrettify={(l) => togglePrettifyLog(l.uuid)}
                isNew={newLogUuids?.has(log.uuid) ?? false}
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
    newLogUuids,
}: VirtualizedLogsListProps): JSX.Element {
    const {
        id,
        pinnedLogs,
        expandedLogIds,
        cursorIndex,
        scrollToCursorRequest,
        columns: columnConfigs,
        selectedLogIds,
        prettifiedLogIds,
    } = useValues(logsViewerLogic)
    const {
        togglePinLog,
        userSetCursorIndex,
        removeColumn,
        setColumnWidth,
        moveColumn,
        selectLogRange,
        togglePrettifyLog,
        setFocused,
        setVisibleRowRange,
    } = useActions(logsViewerLogic)
    const { openLogDetails } = useActions(logDetailsModalLogic)

    const containerRef = useRef<HTMLDivElement>(null)

    const { shouldLoadMore } = useValues(virtualizedLogsListLogic({ id }))
    const { setContainerWidth } = useActions(virtualizedLogsListLogic({ id }))
    const listRef = useListRef(null)
    const autosizerWidthRef = useRef<number>(0)

    const dynamicRowHeight = useDynamicRowHeight({ defaultRowHeight: DEFAULT_ROW_HEIGHT })

    // Ref for flexWidth — updated in AutoSizer callback, read by message column
    // render function. Avoids rebuilding columns on every resize.
    const flexWidthRef = useRef<number | undefined>(undefined)

    // Ref for dataSource — read by ControlsHeader for select-all so it
    // operates on the correct list (main logs vs pinned logs).
    const dataSourceRef = useRef<ParsedLogMessage[]>(dataSource)
    dataSourceRef.current = dataSource

    const { customColumnAliases } = useValues(logsViewerDataLogic({ id }))

    // Server aliases are keyed by the expression that produced them, so map each custom column
    // to its alias by expression. This stays correct when columns are reordered without a re-fetch.
    const aliasById = useMemo(() => {
        const customConfigs = columnConfigs.filter((config) => config.type === 'custom' && !!config.expression?.trim())
        return new Map(customConfigs.map((config) => [config.id, customColumnAliases?.[config.expression!.trim()]]))
    }, [columnConfigs, customColumnAliases])

    // Columns memoized on structural deps only — per-row state (selection,
    // expansion, prettify) is read from kea inside cell components. Everything after the
    // pinned controls column is a configured column; there are no special cases here.
    const columns = useMemo(() => {
        const rendering = { tzLabelFormat, orderBy, onChangeOrderBy, wrapBody, prettifyJson, flexWidthRef }
        // Move bounds range over movable columns only — pinned columns sort last and never swap
        const movable = columnConfigs.filter((config) => !isPinnedColumn(config))
        return [
            createControlsColumn({ dataSourceRef }),
            ...columnConfigs.map((config) =>
                createConfiguredColumn({
                    config,
                    alias: aliasById.get(config.id),
                    callbacks: { onResize: setColumnWidth, onRemove: removeColumn, onMove: moveColumn },
                    rendering,
                    isFirst: config === movable[0],
                    isLast: config === movable[movable.length - 1],
                })
            ),
        ]
    }, [
        tzLabelFormat,
        orderBy,
        onChangeOrderBy,
        columnConfigs,
        aliasById,
        setColumnWidth,
        removeColumn,
        moveColumn,
        wrapBody,
        prettifyJson,
    ])

    const minRowWidth = useMemo(() => getColumnsMinRowWidth(columns), [columns])

    // Scroll to cursor when requested (subscription fires when cursorIndex changes)
    useEffect(() => {
        if (!disableCursor && cursorIndex !== null && cursorIndex >= 0) {
            listRef.current?.scrollToRow({ index: cursorIndex })
            const raf = requestAnimationFrame(() => {
                listRef.current?.scrollToRow({ index: cursorIndex })
            })
            return () => cancelAnimationFrame(raf)
        }
    }, [disableCursor, scrollToCursorRequest, cursorIndex, listRef])

    // Tracks the last range we dispatched so we don't fire setVisibleRowRange on
    // every overscan tick when nothing actually changed.
    const lastVisibleRangeRef = useRef<{ startIndex: number; stopIndex: number } | null>(null)

    const handleRowsRendered = useCallback(
        (
            visibleRows: { startIndex: number; stopIndex: number },
            allRows: { startIndex: number; stopIndex: number }
        ): void => {
            if (
                !disableInfiniteScroll &&
                shouldLoadMore(allRows.stopIndex, dataSource.length, hasMoreLogsToLoad, loading)
            ) {
                onLoadMore?.()
            }

            const prev = lastVisibleRangeRef.current
            if (!prev || prev.startIndex !== visibleRows.startIndex || prev.stopIndex !== visibleRows.stopIndex) {
                lastVisibleRangeRef.current = { startIndex: visibleRows.startIndex, stopIndex: visibleRows.stopIndex }
                setVisibleRowRange(visibleRows.startIndex, visibleRows.stopIndex)
            }
        },
        [
            disableInfiniteScroll,
            shouldLoadMore,
            dataSource.length,
            hasMoreLogsToLoad,
            loading,
            onLoadMore,
            setVisibleRowRange,
        ]
    )

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
            columns,
            cursorIndex,
            expandedLogIds,
            pinnedLogs,
            showPinnedWithOpacity,
            disableCursor,
            wrapBody,
            hasMessageColumn: columnConfigs.some((config) => config.type === 'message'),
            togglePinLog,
            handleLogRowClick,
            rowWidth,
            selectedLogIds,
            selectLogRange,
            userSetCursorIndex,
            prettifiedLogIds,
            togglePrettifyLog,
            dynamicRowHeight,
            newLogUuids,
        }),
        [
            dataSource,
            columns,
            columnConfigs,
            cursorIndex,
            expandedLogIds,
            pinnedLogs,
            showPinnedWithOpacity,
            disableCursor,
            wrapBody,
            togglePinLog,
            handleLogRowClick,
            selectedLogIds,
            selectLogRange,
            userSetCursorIndex,
            prettifiedLogIds,
            togglePrettifyLog,
            dynamicRowHeight,
            newLogUuids,
        ]
    )

    if (dataSource.length === 0 && !loading) {
        return (
            <div className="flex flex-col items-center gap-3 p-8 text-center h-full min-h-40">
                <HedgehogMagnifyingGlass className="w-32 h-32" />
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
                <AutoSizer
                    disableHeight
                    renderProp={({ width }: SizeProps) => {
                        if (width && width !== autosizerWidthRef.current) {
                            autosizerWidthRef.current = width
                            requestAnimationFrame(() => setContainerWidth(width))
                        }
                        const rowWidth = Math.max(width ?? 0, minRowWidth)
                        const adjustedRowWidth = rowWidth - getScrollbarSize()
                        flexWidthRef.current = adjustedRowWidth - getColumnsFixedWidth(columns)

                        return (
                            <div className="overflow-y-hidden overflow-x-auto" style={{ width, height: fixedHeight }}>
                                <LogRowHeader columns={columns} rowWidth={adjustedRowWidth} />
                                <List<LogsListRowProps>
                                    style={{ height: fixedHeight - LOG_ROW_HEADER_HEIGHT, width: rowWidth }}
                                    overscanCount={5}
                                    rowCount={dataSource.length}
                                    rowHeight={dynamicRowHeight}
                                    rowComponent={LogsListRow}
                                    rowProps={createRowProps(adjustedRowWidth)}
                                    listRef={listRef}
                                />
                            </div>
                        )
                    }}
                />
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
            <AutoSizer
                renderProp={({ width, height }: SizeProps) => {
                    if (width && width !== autosizerWidthRef.current) {
                        autosizerWidthRef.current = width
                        requestAnimationFrame(() => setContainerWidth(width))
                    }
                    const rowWidth = Math.max(width ?? 0, minRowWidth)
                    const adjustedRowWidth = rowWidth - getScrollbarSize()
                    flexWidthRef.current = adjustedRowWidth - getColumnsFixedWidth(columns)

                    return height && width ? (
                        <div className="overflow-y-hidden overflow-x-auto" style={{ width, height }}>
                            <LogRowHeader columns={columns} rowWidth={adjustedRowWidth} />
                            <List<LogsListRowProps>
                                style={{ height: height - LOG_ROW_HEADER_HEIGHT, width: rowWidth }}
                                overscanCount={10}
                                rowCount={dataSource.length}
                                rowHeight={dynamicRowHeight}
                                rowComponent={LogsListRow}
                                rowProps={createRowProps(adjustedRowWidth)}
                                listRef={listRef}
                                onRowsRendered={handleRowsRendered}
                            />
                        </div>
                    ) : null
                }}
            />
        </div>
    )
}
