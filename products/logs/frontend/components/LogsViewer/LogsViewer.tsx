import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { TZLabelProps } from 'lib/components/TZLabel'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { DateRange } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { VirtualizedLogsList } from 'products/logs/frontend/components/VirtualizedLogsList/VirtualizedLogsList'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

import { LogDetailsModal } from './LogDetailsModal'
import { LogsSelectionToolbar } from './LogsSelectionToolbar'
import { LogsSparkline, LogsSparklineData } from './LogsViewerSparkline'
import { LogsViewerToolbar } from './LogsViewerToolbar'
import { logsViewerLogic } from './logsViewerLogic'

const SCROLL_INTERVAL_MS = 16 // ~60fps
const SCROLL_AMOUNT_PX = 8

export interface LogsViewerProps {
    tabId: string
    logs: ParsedLogMessage[]
    loading: boolean
    totalLogsCount?: number
    hasMoreLogsToLoad?: boolean
    orderBy: LogsOrderBy
    onChangeOrderBy: (orderBy: LogsOrderBy) => void
    onRefresh?: () => void
    onLoadMore?: () => void
    onAddFilter?: (key: string, value: string, operator?: PropertyOperator, type?: PropertyFilterType) => void
    sparklineData: LogsSparklineData
    sparklineLoading: boolean
    onDateRangeChange: (dateRange: DateRange) => void
}

export function LogsViewer({
    tabId,
    logs,
    loading,
    totalLogsCount,
    hasMoreLogsToLoad,
    orderBy,
    onChangeOrderBy,
    onRefresh,
    onLoadMore,
    onAddFilter,
    sparklineData,
    sparklineLoading,
    onDateRangeChange,
}: LogsViewerProps): JSX.Element {
    return (
        <BindLogic logic={logsViewerLogic} props={{ tabId, logs, orderBy, onAddFilter }}>
            <LogsViewerContent
                loading={loading}
                totalLogsCount={totalLogsCount}
                hasMoreLogsToLoad={hasMoreLogsToLoad}
                orderBy={orderBy}
                onChangeOrderBy={onChangeOrderBy}
                onRefresh={onRefresh}
                onLoadMore={onLoadMore}
                sparklineData={sparklineData}
                sparklineLoading={sparklineLoading}
                onDateRangeChange={onDateRangeChange}
            />
        </BindLogic>
    )
}

interface LogsViewerContentProps {
    loading: boolean
    totalLogsCount?: number
    hasMoreLogsToLoad?: boolean
    orderBy: LogsOrderBy
    onChangeOrderBy: (orderBy: LogsOrderBy) => void
    onRefresh?: () => void
    onLoadMore?: () => void
    sparklineData: LogsSparklineData
    sparklineLoading: boolean
    onDateRangeChange: (dateRange: DateRange) => void
}

function LogsViewerContent({
    loading,
    totalLogsCount,
    hasMoreLogsToLoad,
    orderBy,
    onChangeOrderBy,
    onRefresh,
    onLoadMore,
    sparklineData,
    sparklineLoading,
    onDateRangeChange,
}: LogsViewerContentProps): JSX.Element {
    const {
        tabId,
        wrapBody,
        prettifyJson,
        pinnedLogsArray,
        isFocused,
        cursorLogId,
        logs,
        timezone,
        isSelectionActive,
    } = useValues(logsViewerLogic)
    const {
        moveCursorDown,
        moveCursorUp,
        toggleExpandLog,
        resetCursor,
        toggleSelectLog,
        clearSelection,
        togglePrettifyLog,
    } = useActions(logsViewerLogic)
    const { cellScrollLefts } = useValues(virtualizedLogsListLogic({ tabId }))
    const { setCellScrollLeft } = useActions(virtualizedLogsListLogic({ tabId }))
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
            arrowdown: { action: handleMoveDown, disabled: !isFocused },
            j: { action: handleMoveDown, disabled: !isFocused },
            arrowup: { action: handleMoveUp, disabled: !isFocused },
            k: { action: handleMoveUp, disabled: !isFocused },
            // arrowleft, arrowright, h, l handled by native keydown/keyup for smooth 60fps scrolling
            enter: {
                action: () => {
                    if (cursorLogId) {
                        toggleExpandLog(cursorLogId)
                    }
                },
                disabled: !isFocused,
            },
            r: {
                action: () => {
                    if (onRefresh && !loading) {
                        resetCursor()
                        onRefresh()
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
                    if (isSelectionActive) {
                        clearSelection()
                    }
                },
                disabled: !isFocused,
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
            cursorLogId,
            toggleExpandLog,
            onRefresh,
            loading,
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
        <div className="flex flex-col gap-2 h-full">
            <LogsSparkline
                sparklineData={sparklineData}
                sparklineLoading={sparklineLoading}
                onDateRangeChange={onDateRangeChange}
                displayTimezone={timezone}
            />
            <SceneDivider />
            <LogsViewerToolbar totalLogsCount={totalLogsCount} orderBy={orderBy} onChangeOrderBy={onChangeOrderBy} />
            <LogsSelectionToolbar />
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
                />
            )}

            <VirtualizedLogsList
                dataSource={logs}
                loading={loading}
                wrapBody={wrapBody}
                prettifyJson={prettifyJson}
                tzLabelFormat={tzLabelFormat}
                showPinnedWithOpacity
                hasMoreLogsToLoad={hasMoreLogsToLoad}
                onLoadMore={onLoadMore}
            />

            <LogDetailsModal timezone={timezone} />
        </div>
    )
}
