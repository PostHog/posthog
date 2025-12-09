import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { TZLabelProps } from 'lib/components/TZLabel'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { cn } from 'lib/utils/css-classes'

import { VirtualizedLogsList } from 'products/logs/frontend/components/VirtualizedLogsList/VirtualizedLogsList'
import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

import { LogsViewerToolbar } from './LogsViewerToolbar'
import { logsViewerLogic } from './logsViewerLogic'

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
}: LogsViewerProps): JSX.Element {
    return (
        <BindLogic logic={logsViewerLogic} props={{ tabId, logs, orderBy }}>
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
    const { wrapBody, prettifyJson, pinnedLogsArray, isFocused, getCursorLogId, linkToLogId, logs, logsCount } =
        useValues(logsViewerLogic)
    const { setFocused, moveCursorDown, moveCursorUp, toggleExpandLog, resetCursor, setCursorToLogId } =
        useActions(logsViewerLogic)
    const containerRef = useRef<HTMLDivElement>(null)

    const cursorLogId = getCursorLogId(logs)

    // Reset cursor when logs are cleared (e.g., new query starts)
    useEffect(() => {
        if (logsCount === 0) {
            resetCursor()
        }
    }, [logsCount, resetCursor])

    // Position cursor at linked log when deep linking (URL -> cursor)
    useEffect(() => {
        if (linkToLogId && logsCount > 0) {
            setCursorToLogId(linkToLogId, logs)
            containerRef.current?.focus()
        }
    }, [linkToLogId, logsCount, logs, setCursorToLogId])

    const tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'> = {
        formatDate: 'YYYY-MM-DD',
        formatTime: 'HH:mm:ss.SSS',
    }

    useKeyboardHotkeys(
        {
            arrowdown: { action: () => moveCursorDown(logsCount), disabled: !isFocused },
            j: { action: () => moveCursorDown(logsCount), disabled: !isFocused },
            arrowup: { action: () => moveCursorUp(logsCount), disabled: !isFocused },
            k: { action: () => moveCursorUp(logsCount), disabled: !isFocused },
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
        [
            isFocused,
            logs.length,
            cursorLogId,
            toggleExpandLog,
            onRefresh,
            loading,
            resetCursor,
            moveCursorDown,
            moveCursorUp,
        ]
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
                <div className="border rounded-t bg-card shadow-sm">
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
            <div className={cn('border bg-card flex-1 min-h-0', pinnedLogsArray.length > 0 ? 'rounded-b' : 'rounded')}>
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
