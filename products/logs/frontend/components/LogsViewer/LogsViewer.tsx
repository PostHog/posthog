import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { TZLabelProps } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { DateRange, LogsSparklineBreakdownBy } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { LogsFilterBar } from 'products/logs/frontend/components/LogsViewer/Filters/LogsFilterBar'
import { LogsFilterBar as LogsFilterBarV2 } from 'products/logs/frontend/components/LogsViewer/Filters/LogsFilterBar/LogsFilterBar'
import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { VirtualizedLogsList } from 'products/logs/frontend/components/VirtualizedLogsList/VirtualizedLogsList'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

import { LogDetailsModal } from './LogDetailsModal'
import { logDetailsModalLogic } from './LogDetailsModal/logDetailsModalLogic'
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
    onChangeOrderBy: (orderBy: LogsOrderBy, source: 'header' | 'toolbar') => void
    onRefresh?: () => void
    onLoadMore?: () => void
    onAddFilter?: (key: string, value: string, operator?: PropertyOperator, type?: PropertyFilterType) => void
    sparklineData: LogsSparklineData
    sparklineLoading: boolean
    onDateRangeChange: (dateRange: DateRange) => void
    sparklineBreakdownBy: LogsSparklineBreakdownBy
    onSparklineBreakdownByChange: (breakdownBy: LogsSparklineBreakdownBy) => void
    onExpandTimeRange?: () => void
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
    sparklineBreakdownBy,
    onSparklineBreakdownByChange,
    onExpandTimeRange,
}: LogsViewerProps): JSX.Element {
    return (
        <BindLogic logic={logsViewerConfigLogic} props={{ id: tabId }}>
            <BindLogic logic={logDetailsModalLogic} props={{ tabId }}>
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
                        sparklineBreakdownBy={sparklineBreakdownBy}
                        onSparklineBreakdownByChange={onSparklineBreakdownByChange}
                        onExpandTimeRange={onExpandTimeRange}
                    />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

interface LogsViewerContentProps {
    loading: boolean
    totalLogsCount?: number
    hasMoreLogsToLoad?: boolean
    orderBy: LogsOrderBy
    onChangeOrderBy: (orderBy: LogsOrderBy, source: 'header' | 'toolbar') => void
    onRefresh?: () => void
    onLoadMore?: () => void
    sparklineData: LogsSparklineData
    sparklineLoading: boolean
    onDateRangeChange: (dateRange: DateRange) => void
    sparklineBreakdownBy: LogsSparklineBreakdownBy
    onSparklineBreakdownByChange: (breakdownBy: LogsSparklineBreakdownBy) => void
    onExpandTimeRange?: () => void
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
    sparklineBreakdownBy,
    onSparklineBreakdownByChange,
    onExpandTimeRange,
}: LogsViewerContentProps): JSX.Element {
    const newLogsFilterBar = useFeatureFlag('NEW_LOGS_FILTER_BAR')
    const {
        tabId,
        wrapBody,
        prettifyJson,
        pinnedLogsArray,
        isFocused,
        cursorIndex,
        cursorLogId,
        logs,
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
            arrowdown: { action: handleMoveDown, disabled: !keyboardNavEnabled },
            j: { action: handleMoveDown, disabled: !keyboardNavEnabled },
            arrowup: { action: handleMoveUp, disabled: !keyboardNavEnabled },
            k: { action: handleMoveUp, disabled: !keyboardNavEnabled },
            // arrowleft, arrowright, h, l handled by native keydown/keyup for smooth 60fps scrolling
            enter: {
                action: () => {
                    if (cursorIndex !== null && logs[cursorIndex]) {
                        openLogDetails(logs[cursorIndex])
                    }
                },
                disabled: !keyboardNavEnabled,
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
            logs,
            openLogDetails,
            closeLogDetails,
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
            {newLogsFilterBar ? <LogsFilterBarV2 /> : <LogsFilterBar />}
            <LogsSparkline
                sparklineData={sparklineData}
                sparklineLoading={sparklineLoading}
                onDateRangeChange={onDateRangeChange}
                displayTimezone={timezone}
                breakdownBy={sparklineBreakdownBy}
                onBreakdownByChange={onSparklineBreakdownByChange}
            />
            <SceneDivider />
            <LogsViewerToolbar
                totalLogsCount={totalLogsCount}
                orderBy={orderBy}
                onChangeOrderBy={(newOrderBy) => onChangeOrderBy(newOrderBy, 'toolbar')}
            />
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
                    orderBy={orderBy}
                    onChangeOrderBy={(newOrderBy) => onChangeOrderBy(newOrderBy, 'header')}
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
                onExpandTimeRange={onExpandTimeRange}
                orderBy={orderBy}
                onChangeOrderBy={(newOrderBy) => onChangeOrderBy(newOrderBy, 'header')}
            />

            <LogDetailsModal timezone={timezone} />
        </div>
    )
}
