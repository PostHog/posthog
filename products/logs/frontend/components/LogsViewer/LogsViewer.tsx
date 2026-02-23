import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { TZLabelProps } from 'lib/components/TZLabel'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'

import { LogsFilterBar } from 'products/logs/frontend/components/LogsViewer/Filters/LogsFilterBar/LogsFilterBar'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerDataLogic } from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'
import { logsExportLogic } from 'products/logs/frontend/components/LogsViewer/logsExportLogic'
import { VirtualizedLogsList } from 'products/logs/frontend/components/VirtualizedLogsList/VirtualizedLogsList'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'

import { LogDetailsModal } from './LogDetailsModal'
import { logDetailsModalLogic } from './LogDetailsModal/logDetailsModalLogic'
import { LogsSparkline } from './LogsViewerSparkline'
import { LogsViewerToolbar } from './LogsViewerToolbar'
import { logsViewerLogic } from './logsViewerLogic'

const SCROLL_INTERVAL_MS = 16 // ~60fps
const SCROLL_AMOUNT_PX = 8

export interface LogsViewerProps {
    id: string
}

export function LogsViewer({ id }: LogsViewerProps): JSX.Element {
    return (
        <BindLogic logic={logsViewerFiltersLogic} props={{ id }}>
            <BindLogic logic={logsViewerConfigLogic} props={{ id }}>
                <BindLogic logic={logsViewerDataLogic} props={{ id }}>
                    <BindLogic logic={logDetailsModalLogic} props={{ id }}>
                        <BindLogic logic={logsViewerLogic} props={{ id }}>
                            <BindLogic logic={logsExportLogic} props={{ id }}>
                                <LogsViewerContent />
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function LogsViewerContent(): JSX.Element {
    const {
        id,
        wrapBody,
        prettifyJson,
        pinnedLogsArray,
        isFocused,
        cursorIndex,
        cursorLogId,
        timezone,
        isSelectionActive,
        keyboardNavEnabled,
        isLogDetailsOpen,
    } = useValues(logsViewerLogic)
    const {
        moveCursorDown,
        moveCursorUp,
        openLogDetails,
        closeLogDetails,
        resetCursor,
        toggleSelectLog,
        clearSelection,
        togglePrettifyLog,
    } = useActions(logsViewerLogic)
    const { orderBy, sparklineBreakdownBy } = useValues(logsViewerConfigLogic)
    const { setOrderBy, setSparklineBreakdownBy } = useActions(logsViewerConfigLogic)
    const { logsLoading, parsedLogs, sparklineData, sparklineLoading, hasMoreLogsToLoad, totalLogsMatchingFilters } =
        useValues(logsViewerDataLogic)
    const { runQuery, fetchNextLogsPage } = useActions(logsViewerDataLogic)
    const { setDateRange, zoomDateRange } = useActions(logsViewerFiltersLogic)
    const { cellScrollLefts } = useValues(virtualizedLogsListLogic({ id }))
    const { setCellScrollLeft } = useActions(virtualizedLogsListLogic({ id }))
    const messageScrollLeft = cellScrollLefts['message'] ?? 0
    const scrollLeftRef = useRef(messageScrollLeft)
    scrollLeftRef.current = messageScrollLeft

    const scrollIntervalRef = useRef<number | null>(null)

    const scrollMessage = useCallback(
        (direction: 'left' | 'right'): void => {
            const newScrollLeft =
                direction === 'left'
                    ? Math.max(0, scrollLeftRef.current - SCROLL_AMOUNT_PX)
                    : scrollLeftRef.current + SCROLL_AMOUNT_PX
            scrollLeftRef.current = newScrollLeft
            setCellScrollLeft('message', newScrollLeft)
        },
        [setCellScrollLeft]
    )

    const startScrolling = useCallback(
        (direction: 'left' | 'right'): void => {
            if (scrollIntervalRef.current !== null) {
                return // Already scrolling
            }
            scrollMessage(direction)
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

    // Handle keyboard scroll with keydown/keyup for smooth 60fps scrolling
    useEffect(() => {
        if (!isFocused || wrapBody) {
            return
        }

        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.repeat) {
                return // Ignore OS key repeat, we have our own interval
            }
            if (e.key === 'ArrowLeft' || e.key === 'h') {
                e.preventDefault()
                startScrolling('left')
            } else if (e.key === 'ArrowRight' || e.key === 'l') {
                e.preventDefault()
                startScrolling('right')
            }
        }

        const handleKeyUp = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowLeft' || e.key === 'h' || e.key === 'ArrowRight' || e.key === 'l') {
                stopScrolling()
            }
        }

        window.addEventListener('keydown', handleKeyDown)
        window.addEventListener('keyup', handleKeyUp)

        return () => {
            window.removeEventListener('keydown', handleKeyDown)
            window.removeEventListener('keyup', handleKeyUp)
            stopScrolling()
        }
    }, [isFocused, wrapBody, startScrolling, stopScrolling])

    const tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime' | 'displayTimezone'> = {
        formatDate: 'YYYY-MM-DD',
        formatTime: 'HH:mm:ss.SSS',
        displayTimezone: timezone,
    }

    const handleMoveDown = useCallback(
        (e: KeyboardEvent): void => {
            moveCursorDown(e.shiftKey)
        },
        [moveCursorDown]
    )

    const handleMoveUp = useCallback(
        (e: KeyboardEvent): void => {
            moveCursorUp(e.shiftKey)
        },
        [moveCursorUp]
    )

    useKeyboardHotkeys(
        {
            arrowdown: { action: handleMoveDown, disabled: !keyboardNavEnabled },
            j: { action: handleMoveDown, disabled: !keyboardNavEnabled },
            arrowup: { action: handleMoveUp, disabled: !keyboardNavEnabled },
            k: { action: handleMoveUp, disabled: !keyboardNavEnabled },
            // arrowleft, arrowright, h, l handled by native keydown/keyup for smooth 60fps scrolling
            enter: {
                action: () => {
                    if (cursorIndex !== null && parsedLogs[cursorIndex]) {
                        openLogDetails(parsedLogs[cursorIndex])
                    }
                },
                disabled: !keyboardNavEnabled,
            },
            r: {
                action: () => {
                    if (!logsLoading) {
                        resetCursor()
                        runQuery()
                    }
                },
                disabled: !isFocused,
            },
            space: {
                action: (e: KeyboardEvent) => {
                    e.preventDefault()
                    if (cursorLogId) {
                        toggleSelectLog(cursorLogId)
                    }
                },
                disabled: !isFocused,
            },
            escape: {
                action: () => {
                    if (isLogDetailsOpen) {
                        closeLogDetails()
                    } else if (isSelectionActive) {
                        clearSelection()
                    }
                },
                disabled: !keyboardNavEnabled,
            },
            p: {
                action: () => {
                    if (cursorLogId) {
                        togglePrettifyLog(cursorLogId)
                    }
                },
                disabled: !isFocused,
            },
        },
        [
            isFocused,
            keyboardNavEnabled,
            isLogDetailsOpen,
            cursorIndex,
            parsedLogs,
            openLogDetails,
            closeLogDetails,
            runQuery,
            logsLoading,
            resetCursor,
            moveCursorDown,
            moveCursorUp,
            toggleSelectLog,
            isSelectionActive,
            clearSelection,
            togglePrettifyLog,
        ]
    )

    return (
        <div className="flex flex-col gap-2 h-full" data-attr="logs-viewer">
            <LogsFilterBar />
            <LogsSparkline
                sparklineData={sparklineData}
                sparklineLoading={sparklineLoading}
                onDateRangeChange={setDateRange}
                displayTimezone={timezone}
                breakdownBy={sparklineBreakdownBy}
                onBreakdownByChange={setSparklineBreakdownBy}
            />
            <SceneDivider />
            <LogsViewerToolbar
                totalLogsCount={sparklineLoading ? undefined : totalLogsMatchingFilters}
                orderBy={orderBy}
                onChangeOrderBy={(newOrderBy) => setOrderBy(newOrderBy, 'toolbar')}
            />
            {pinnedLogsArray.length > 0 && (
                <VirtualizedLogsList
                    dataSource={pinnedLogsArray}
                    loading={false}
                    wrapBody={wrapBody}
                    prettifyJson={prettifyJson}
                    tzLabelFormat={tzLabelFormat}
                    fixedHeight={250}
                    disableInfiniteScroll
                    disableCursor
                    orderBy={orderBy}
                    onChangeOrderBy={(newOrderBy) => setOrderBy(newOrderBy, 'header')}
                />
            )}

            <VirtualizedLogsList
                dataSource={parsedLogs}
                loading={logsLoading}
                wrapBody={wrapBody}
                prettifyJson={prettifyJson}
                tzLabelFormat={tzLabelFormat}
                showPinnedWithOpacity
                hasMoreLogsToLoad={hasMoreLogsToLoad}
                onLoadMore={fetchNextLogsPage}
                onExpandTimeRange={() => zoomDateRange(2)}
                orderBy={orderBy}
                onChangeOrderBy={(newOrderBy) => setOrderBy(newOrderBy, 'header')}
            />

            <LogDetailsModal timezone={timezone} />
        </div>
    )
}
