import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'

import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { PropertyOperator } from '~/types'

import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

import type { logsViewerLogicType } from './logsViewerLogicType'

export interface VisibleLogsTimeRange {
    date_from: string
    date_to: string
}

export interface LogCursor {
    logIndex: number
    attributeIndex: number | null // null = at row level, number = at specific attribute
}

export interface LogsViewerLogicProps {
    tabId: string
    logs: ParsedLogMessage[]
    orderBy: LogsOrderBy
    onAddFilter?: (key: string, value: string, operator?: PropertyOperator) => void
}

export const logsViewerLogic = kea<logsViewerLogicType>([
    props({} as LogsViewerLogicProps),
    key((props) => props.tabId),
    path((tabId) => ['products', 'logs', 'frontend', 'components', 'LogsViewer', 'logsViewerLogic', tabId]),

    actions({
        // Display options
        setWrapBody: (wrapBody: boolean) => ({ wrapBody }),
        setPrettifyJson: (prettifyJson: boolean) => ({ prettifyJson }),

        // Pinning
        togglePinLog: (log: ParsedLogMessage) => ({ log }),

        // Focus (for keyboard shortcuts)
        setFocused: (isFocused: boolean) => ({ isFocused }),

        // Cursor (vim-style navigation position, can navigate into expanded log attributes)
        setCursor: (cursor: LogCursor | null) => ({ cursor }),
        setCursorIndex: (index: number | null) => ({ index }), // Convenience: sets cursor to row level
        userSetCursorIndex: (index: number | null) => ({ index }), // User-initiated (click on row)
        userSetCursorAttribute: (logIndex: number, attributeIndex: number) => ({ logIndex, attributeIndex }), // User-initiated (click on attribute)
        resetCursor: true,
        moveCursorDown: true,
        moveCursorUp: true,

        // Expansion
        toggleExpandLog: (logId: string) => ({ logId }),

        // Deep linking - position cursor at a specific log by ID
        setLinkToLogId: (linkToLogId: string | null) => ({ linkToLogId }),
        setCursorToLogId: (logId: string) => ({ logId }),

        // Copy link to log
        copyLinkToLog: (logId: string) => ({ logId }),

        // Sync logs from props
        setLogs: (logs: ParsedLogMessage[]) => ({ logs }),

        // Filter actions (emits to parent via props callback)
        addFilter: (key: string, value: string, operator?: PropertyOperator) => ({ key, value, operator }),

        // Attribute breakdowns (per-log)
        toggleAttributeBreakdown: (logId: string, attributeKey: string) => ({ logId, attributeKey }),

        // Row height recomputation (triggered by child components when content changes)
        recomputeRowHeights: (logIds?: string[]) => ({ logIds }),
    }),

    reducers(({ props }) => ({
        // Synced from props via propsChanged
        logs: [props.logs, { setLogs: (_, { logs }) => logs }],
        wrapBody: [
            true,
            { persist: true },
            {
                setWrapBody: (_, { wrapBody }) => wrapBody,
            },
        ],

        prettifyJson: [
            true,
            { persist: true },
            {
                setPrettifyJson: (_, { prettifyJson }) => prettifyJson,
            },
        ],

        pinnedLogs: [
            {} as Record<string, ParsedLogMessage>,
            { persist: true },
            {
                togglePinLog: (state, { log }) => {
                    if (state[log.uuid]) {
                        const { [log.uuid]: _, ...rest } = state
                        return rest
                    }
                    return { ...state, [log.uuid]: log }
                },
            },
        ],

        isFocused: [
            false,
            {
                setFocused: (_, { isFocused }) => isFocused,
            },
        ],

        cursor: [
            null as LogCursor | null,
            { persist: true },
            {
                setCursor: (_, { cursor }) => cursor,
                setCursorIndex: (_, { index }) => (index !== null ? { logIndex: index, attributeIndex: null } : null),
                userSetCursorIndex: (_, { index }) =>
                    index !== null ? { logIndex: index, attributeIndex: null } : null,
                userSetCursorAttribute: (_, { logIndex, attributeIndex }) => ({ logIndex, attributeIndex }),
                resetCursor: () => null,
            },
        ],

        expandedLogIds: [
            {} as Record<string, boolean>,
            {
                toggleExpandLog: (state, { logId }) => {
                    if (state[logId]) {
                        const { [logId]: _, ...rest } = state
                        return rest
                    }
                    return { ...state, [logId]: true }
                },
            },
        ],

        linkToLogId: [
            null as string | null,
            {
                setLinkToLogId: (_, { linkToLogId }) => linkToLogId,
                // Clear when user actively navigates
                moveCursorDown: () => null,
                moveCursorUp: () => null,
                userSetCursorIndex: () => null,
                userSetCursorAttribute: () => null,
            },
        ],

        expandedAttributeBreakdowns: [
            {} as Record<string, string[]>,
            {
                toggleAttributeBreakdown: (state, { logId, attributeKey }) => {
                    const current = state[logId] || []
                    if (current.includes(attributeKey)) {
                        const updated = current.filter((k) => k !== attributeKey)
                        if (updated.length === 0) {
                            const { [logId]: _, ...rest } = state
                            return rest
                        }
                        return { ...state, [logId]: updated }
                    }
                    return { ...state, [logId]: [...current, attributeKey] }
                },
            },
        ],

        // Tracks requests to recompute row heights - VirtualizedLogsList watches this
        recomputeRowHeightsRequest: [
            null as { logIds?: string[]; timestamp: number } | null,
            {
                recomputeRowHeights: (_, { logIds }) => ({ logIds, timestamp: Date.now() }),
            },
        ],
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.logs !== oldProps.logs) {
            actions.setLogs(props.logs)
        }
    }),

    selectors({
        tabId: [(_, p) => [p.tabId], (tabId: string): string => tabId],

        pinnedLogsArray: [(s) => [s.pinnedLogs], (pinnedLogs): ParsedLogMessage[] => Object.values(pinnedLogs)],

        // Convenience selectors for cursor components
        cursorIndex: [(s) => [s.cursor], (cursor): number | null => cursor?.logIndex ?? null],
        cursorAttributeIndex: [(s) => [s.cursor], (cursor): number | null => cursor?.attributeIndex ?? null],

        cursorLogId: [
            (s) => [s.cursor, s.logs],
            (cursor: LogCursor | null, logs: ParsedLogMessage[]): string | null =>
                cursor !== null && cursor.logIndex >= 0 && cursor.logIndex < logs.length
                    ? logs[cursor.logIndex].uuid
                    : null,
        ],

        visibleLogsTimeRange: [
            (s, p) => [s.logs, p.orderBy],
            (logs: ParsedLogMessage[], orderBy: LogsOrderBy): VisibleLogsTimeRange | null => {
                if (logs.length === 0) {
                    return null
                }
                const firstTimestamp = logs[0].timestamp
                const lastTimestamp = logs[logs.length - 1].timestamp

                if (orderBy === 'latest') {
                    return {
                        date_from: dayjs(lastTimestamp).toISOString(),
                        date_to: dayjs(firstTimestamp).toISOString(),
                    }
                }
                return {
                    date_from: dayjs(firstTimestamp).toISOString(),
                    date_to: dayjs(lastTimestamp).toISOString(),
                }
            },
        ],

        logsCount: [(s) => [s.logs], (logs: ParsedLogMessage[]): number => logs.length],
    }),

    listeners(({ actions, values, props }) => ({
        setLogs: ({ logs }) => {
            if (logs.length === 0) {
                actions.resetCursor()
            }
        },
        addFilter: ({ key, value, operator }) => {
            props.onAddFilter?.(key, value, operator)
        },
        toggleExpandLog: ({ logId }) => {
            // If cursor is at attribute level, check if we just collapsed the row it's in
            if (values.cursor?.attributeIndex !== null) {
                const cursorLog = values.logs[values.cursor?.logIndex ?? 0]
                const cursorIsInThisLog = cursorLog?.uuid === logId
                const thisLogWasJustCollapsed = !values.expandedLogIds[logId]

                if (cursorIsInThisLog && thisLogWasJustCollapsed) {
                    actions.setCursor({ logIndex: values.cursor?.logIndex ?? 0, attributeIndex: null })
                }
            }

            actions.recomputeRowHeights([logId])
        },
        moveCursorDown: () => {
            const { logs } = values
            if (logs.length === 0) {
                return
            }

            const cursor = values.cursor
            if (cursor === null) {
                // No cursor - start at first row
                actions.setCursor({ logIndex: 0, attributeIndex: null })
                return
            }

            const currentLog = logs[cursor.logIndex]
            const isExpanded = !!values.expandedLogIds[currentLog?.uuid]
            const attributeKeys = currentLog ? Object.keys(currentLog.attributes) : []
            const attributeCount = attributeKeys.length

            if (cursor.attributeIndex === null) {
                // At row level
                if (isExpanded && attributeCount > 0) {
                    // Enter into attributes
                    actions.setCursor({ logIndex: cursor.logIndex, attributeIndex: 0 })
                } else if (cursor.logIndex < logs.length - 1) {
                    // Move to next row
                    actions.setCursor({ logIndex: cursor.logIndex + 1, attributeIndex: null })
                }
            } else {
                // At attribute level
                if (cursor.attributeIndex < attributeCount - 1) {
                    // Move to next attribute
                    actions.setCursor({ logIndex: cursor.logIndex, attributeIndex: cursor.attributeIndex + 1 })
                } else if (cursor.logIndex < logs.length - 1) {
                    // Move to next row
                    actions.setCursor({ logIndex: cursor.logIndex + 1, attributeIndex: null })
                }
            }
        },
        moveCursorUp: () => {
            const { logs } = values
            if (logs.length === 0) {
                return
            }

            const cursor = values.cursor
            if (cursor === null) {
                // No cursor - start at last row
                actions.setCursor({ logIndex: logs.length - 1, attributeIndex: null })
                return
            }

            if (cursor.attributeIndex === null) {
                // At row level
                if (cursor.logIndex > 0) {
                    // Check if previous row is expanded
                    const prevLog = logs[cursor.logIndex - 1]
                    const isPrevExpanded = !!values.expandedLogIds[prevLog?.uuid]
                    const prevAttributeKeys = prevLog ? Object.keys(prevLog.attributes) : []
                    const prevAttributeCount = prevAttributeKeys.length

                    if (isPrevExpanded && prevAttributeCount > 0) {
                        // Enter previous row at last attribute
                        actions.setCursor({ logIndex: cursor.logIndex - 1, attributeIndex: prevAttributeCount - 1 })
                    } else {
                        // Move to previous row
                        actions.setCursor({ logIndex: cursor.logIndex - 1, attributeIndex: null })
                    }
                }
            } else {
                // At attribute level
                if (cursor.attributeIndex > 0) {
                    // Move to previous attribute
                    actions.setCursor({ logIndex: cursor.logIndex, attributeIndex: cursor.attributeIndex - 1 })
                } else {
                    // Move to row level
                    actions.setCursor({ logIndex: cursor.logIndex, attributeIndex: null })
                }
            }
        },
        setCursorToLogId: ({ logId }) => {
            const index = values.logs.findIndex((log) => log.uuid === logId)
            if (index !== -1) {
                actions.setCursor({ logIndex: index, attributeIndex: null })
            }
        },
        copyLinkToLog: ({ logId }) => {
            const url = new URL(window.location.href)
            url.searchParams.set('linkToLogId', logId)
            if (values.visibleLogsTimeRange) {
                url.searchParams.set(
                    'dateRange',
                    JSON.stringify({
                        date_from: values.visibleLogsTimeRange.date_from,
                        date_to: values.visibleLogsTimeRange.date_to,
                        explicitDate: true,
                    })
                )
            }
            if (values.logsCount > 0) {
                url.searchParams.set('initialLogsLimit', String(values.logsCount))
            }
            void copyToClipboard(url.toString(), 'link to log')
        },
    })),

    tabAwareUrlToAction(({ actions, values }) => ({
        '*': (_, searchParams) => {
            // Support both new (linkToLogId) and legacy (highlightedLogId) URL params
            const linkToLogId = (searchParams.linkToLogId ?? searchParams.highlightedLogId) as string | undefined
            if (linkToLogId && linkToLogId !== values.linkToLogId) {
                actions.setLinkToLogId(linkToLogId)
            }
        },
    })),

    tabAwareActionToUrl(() => {
        const clearLinkToLogIdFromUrl = ():
            | [string, Record<string, any>, Record<string, any>, { replace: boolean }]
            | void => {
            const url = new URL(window.location.href)
            const hasLinkParam = url.searchParams.has('linkToLogId') || url.searchParams.has('highlightedLogId')
            if (hasLinkParam) {
                url.searchParams.delete('linkToLogId')
                url.searchParams.delete('highlightedLogId')
                return [url.pathname, Object.fromEntries(url.searchParams), {}, { replace: true }]
            }
        }
        return {
            // Clear URL param when user actively navigates
            moveCursorDown: clearLinkToLogIdFromUrl,
            moveCursorUp: clearLinkToLogIdFromUrl,
            userSetCursorIndex: clearLinkToLogIdFromUrl,
            userSetCursorAttribute: clearLinkToLogIdFromUrl,
        }
    }),
])
