import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { TZLabelProps } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { UniversalFiltersGroup } from '~/types'

import { LogsGroupByResults } from 'products/logs/frontend/components/LogsGroupBy/LogsGroupByResults'
import { LogsPatterns } from 'products/logs/frontend/components/LogsPatterns/LogsPatterns'
import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import { logsViewerDataLogic } from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'
import { FacetRail } from 'products/logs/frontend/components/LogsViewer/FacetRail/FacetRail'
import { LogsFilterBar } from 'products/logs/frontend/components/LogsViewer/Filters/LogsFilterBar/LogsFilterBar'
import { LogsQueryBar } from 'products/logs/frontend/components/LogsViewer/Filters/LogsFilterBar/LogsQueryBar'
import { logsFilterHistoryLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsFilterHistoryLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsExportLogic } from 'products/logs/frontend/components/LogsViewer/logsExportLogic'
import { VirtualizedLogsList } from 'products/logs/frontend/components/VirtualizedLogsList/VirtualizedLogsList'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'

import { LogDetailsModal } from './LogDetailsModal'
import { logDetailsModalLogic } from './LogDetailsModal/logDetailsModalLogic'
import { LogsDisplayBar } from './LogsDisplayBar'
import { logsViewerLogic } from './logsViewerLogic'
import { LogsSparkline } from './LogsViewerSparkline'

const SCROLL_INTERVAL_MS = 16 // ~60fps
const SCROLL_AMOUNT_PX = 8

export interface LogsViewerProps {
    id: string
    showFullScreenButton?: boolean
    showSavedViewsButton?: boolean
    initialFilters?: Partial<LogsViewerFilters>
    // Filters enforced by the embedding scene. Merged into the user-editable filterGroup
    // and rendered without an X so users can't accidentally drop the scope.
    pinnedFilters?: UniversalFiltersGroup
    // Hide the filter bar (levels/services/search/date range) entirely. For embeds where the
    // scope is fixed by `pinnedFilters` and editing filters in place isn't wanted. @default true
    showFilterBar?: boolean
}

export function LogsViewer({
    id,
    showFullScreenButton = true,
    showSavedViewsButton = false,
    initialFilters,
    pinnedFilters,
    showFilterBar = true,
}: LogsViewerProps): JSX.Element {
    return (
        <BindLogic logic={logsViewerFiltersLogic} props={{ id, initialFilters, pinnedFilters }}>
            <BindLogic logic={logsViewerConfigLogic} props={{ id }}>
                <BindLogic logic={logsViewerDataLogic} props={{ id }}>
                    <BindLogic logic={logDetailsModalLogic} props={{ id }}>
                        <BindLogic logic={logsViewerLogic} props={{ id }}>
                            <BindLogic logic={logsExportLogic} props={{ id }}>
                                <BindLogic logic={logsFilterHistoryLogic} props={{ id }}>
                                    <LogsViewerContent
                                        showFullScreenButton={showFullScreenButton}
                                        showSavedViewsButton={showSavedViewsButton}
                                        showFilterBar={showFilterBar}
                                    />
                                </BindLogic>
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function LogsViewerContent({
    showFullScreenButton,
    showSavedViewsButton,
    showFilterBar,
}: {
    showFullScreenButton: boolean
    showSavedViewsButton: boolean
    showFilterBar: boolean
}): JSX.Element {
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
    const { orderBy, sparklineBreakdownBy, sparklineCollapsed, facetRailCollapsed, viewMode, groupBy } =
        useValues(logsViewerConfigLogic)
    const { setOrderBy, setSparklineBreakdownBy, toggleSparklineCollapsed } = useActions(logsViewerConfigLogic)
    const {
        logsLoading,
        parsedLogs,
        sparklineData,
        sparklineLoading,
        sparklineIncompleteBarIndices,
        hasMoreLogsToLoad,
        totalLogsMatchingFilters,
    } = useValues(logsViewerDataLogic)
    const { runQuery, fetchNextLogsPage } = useActions(logsViewerDataLogic)
    const { setDateRange, zoomDateRange } = useActions(logsViewerFiltersLogic)
    const showFacetRail = useFeatureFlag('LOGS_FACET_RAIL')
    const showPatternsView = useFeatureFlag('LOGS_PATTERNS_VIEW')
    const showGroupBy = useFeatureFlag('LOGS_GROUP_BY')
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

    const sparklineSection = (
        <>
            <LogsSparkline
                sparklineData={sparklineData}
                sparklineLoading={sparklineLoading}
                onDateRangeChange={setDateRange}
                displayTimezone={timezone}
                breakdownBy={sparklineBreakdownBy}
                onBreakdownByChange={setSparklineBreakdownBy}
                collapsed={sparklineCollapsed}
                onToggleCollapse={toggleSparklineCollapsed}
                incompleteBarIndices={sparklineIncompleteBarIndices}
            />
            <SceneDivider />
        </>
    )

    const filterBar = showFilterBar ? (
        <LogsFilterBar showSavedViewsButton={showSavedViewsButton} showFullScreenButton={showFullScreenButton} />
    ) : null

    const displayBarProps = {
        id,
        totalLogsCount: sparklineLoading ? undefined : totalLogsMatchingFilters,
    }

    const logList = (
        <>
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
        </>
    )

    // Patterns is a mode of the Viewer, not a separate tab: it swaps only the results region
    // and reuses the same filter bar / FacetRail / date range (shared via logsViewerFiltersLogic).
    // Gate on the flag too, so the patterns query stays unreachable when the flag is off regardless
    // of the (non-persisted) viewMode state.
    const inPatternsMode = showPatternsView && viewMode === 'patterns'
    // Group-by (prototype, logs-group-by flag): an active grouping swaps the Logs lens's results
    // for the grouped table. Double-gated like Patterns so it's unreachable with the flag off.
    const inGroupByMode = showGroupBy && !inPatternsMode && groupBy !== null
    const resultsRegion = inPatternsMode ? (
        <LogsPatterns id={id} />
    ) : inGroupByMode && groupBy ? (
        <LogsGroupByResults groupBy={groupBy} />
    ) : (
        logList
    )

    // Both layouts share the same results column; only the results bar above it differs (the facet-rail
    // layout adds the rail toggle). The bar owns the Logs⇄Patterns switch and hides its Logs-only tools
    // in Patterns mode, so it renders in both modes — keeping the frame (toggle, count) persistent.
    const resultsColumn = (bar: JSX.Element): JSX.Element => (
        <>
            {bar}
            {resultsRegion}
        </>
    )

    if (showFacetRail) {
        // Three-tier layout: query bar (ask a question) above the sparkline, the sparkline, then a
        // row of [facet rail | display bar (operate on the data) + the log lists].
        return (
            <div className="flex flex-col gap-2 h-full" data-attr="logs-viewer">
                <LogsQueryBar showSavedViewsButton={showSavedViewsButton} showFullScreenButton={showFullScreenButton} />
                {sparklineSection}
                <div className="flex flex-row gap-2 flex-1 min-h-0">
                    {!facetRailCollapsed && <FacetRail id={id} />}
                    <div className="flex flex-col gap-2 flex-1 min-w-0">
                        {resultsColumn(<LogsDisplayBar {...displayBarProps} showFacetRailToggle />)}
                    </div>
                </div>
                <LogDetailsModal timezone={timezone} />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 h-full" data-attr="logs-viewer">
            {sparklineSection}
            {filterBar}
            {resultsColumn(<LogsDisplayBar {...displayBarProps} />)}
            <LogDetailsModal timezone={timezone} />
        </div>
    )
}
