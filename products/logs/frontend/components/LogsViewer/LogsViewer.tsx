import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { TZLabelProps } from 'lib/components/TZLabel'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { cn } from 'lib/utils/css-classes'

import { PropertyOperator } from '~/types'

import { VirtualizedLogsList } from 'products/logs/frontend/components/VirtualizedLogsList/VirtualizedLogsList'
import { virtualizedLogsListLogic } from 'products/logs/frontend/components/VirtualizedLogsList/virtualizedLogsListLogic'
import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

import { LogsViewerToolbar } from './LogsViewerToolbar'
import { logsViewerLogic } from './logsViewerLogic'

const SCROLL_INTERVAL_MS = 16 // ~60fps

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
    onAddFilter?: (key: string, value: string, operator?: PropertyOperator) => void
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
}

function LogsViewerContent({
    loading,
    totalLogsCount,
    hasMoreLogsToLoad,
    orderBy,
    onChangeOrderBy,
    onRefresh,
    onLoadMore,
}: LogsViewerContentProps): JSX.Element {
    const { wrapBody, prettifyJson, pinnedLogsArray, isFocused, cursorLogId, linkToLogId, logs, logsCount } =
        useValues(logsViewerLogic)
    const { setFocused, moveCursorDown, moveCursorUp, toggleExpandLog, resetCursor, setCursorToLogId } =
        useActions(logsViewerLogic)
    const { messageScrollLeft } = useValues(virtualizedLogsListLogic)
    const { setMessageScrollLeft } = useActions(virtualizedLogsListLogic)
    const containerRef = useRef<HTMLDivElement>(null)
    const scrollLeftRef = useRef(messageScrollLeft)
    scrollLeftRef.current = messageScrollLeft

    const scrollIntervalRef = useRef<number | null>(null)

    const scrollMessage = useCallback(
        (direction: 'left' | 'right'): void => {
            const scrollAmount = 8
            const newScrollLeft =
                direction === 'left'
                    ? Math.max(0, scrollLeftRef.current - scrollAmount)
                    : scrollLeftRef.current + scrollAmount
            scrollLeftRef.current = newScrollLeft
            setMessageScrollLeft(newScrollLeft)
        },
        [setMessageScrollLeft]
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

    // Position cursor at linked log when deep linking (URL -> cursor)
    useEffect(() => {
        if (linkToLogId && logsCount > 0) {
            setCursorToLogId(linkToLogId)
            containerRef.current?.focus()
        }
    }, [linkToLogId, logsCount, setCursorToLogId])

    const tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'> = {
        formatDate: 'YYYY-MM-DD',
        formatTime: 'HH:mm:ss.SSS',
    }

    useKeyboardHotkeys(
        {
            arrowdown: { action: () => moveCursorDown(), disabled: !isFocused },
            j: { action: () => moveCursorDown(), disabled: !isFocused },
            arrowup: { action: () => moveCursorUp(), disabled: !isFocused },
            k: { action: () => moveCursorUp(), disabled: !isFocused },
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
        },
        [isFocused, cursorLogId, toggleExpandLog, onRefresh, loading, resetCursor, moveCursorDown, moveCursorUp]
    )

    return (
        <div
            ref={containerRef}
            className="flex flex-col gap-2 h-full outline-none focus:ring-1 focus:ring-border-bold focus:ring-offset-1 rounded"
            tabIndex={0}
            onFocus={() => {
                setFocused(true)
                containerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
            }}
            onBlur={() => setFocused(false)}
        >
            <div className="py-2">
                <LogsViewerToolbar
                    totalLogsCount={totalLogsCount}
                    orderBy={orderBy}
                    onChangeOrderBy={onChangeOrderBy}
                />
            </div>
            {pinnedLogsArray.length > 0 && (
                <div className="border rounded-t bg-bg-light shadow-sm">
                    <VirtualizedLogsList
                        dataSource={pinnedLogsArray}
                        loading={false}
                        wrapBody={wrapBody}
                        prettifyJson={prettifyJson}
                        tzLabelFormat={tzLabelFormat}
                        showPinnedWithOpacity
                        fixedHeight={250}
                        disableInfiniteScroll
                    />
                </div>
            )}
            <div
                className={cn(
                    'border bg-bg-light flex-1 min-h-0',
                    pinnedLogsArray.length > 0 ? 'rounded-b' : 'rounded'
                )}
            >
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
            </div>
        </div>
    )
}
