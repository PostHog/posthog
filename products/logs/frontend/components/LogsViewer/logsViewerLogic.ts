import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'

import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

import type { logsViewerLogicType } from './logsViewerLogicType'

export interface VisibleLogsTimeRange {
    date_from: string
    date_to: string
}

export interface LogsViewerLogicProps {
    tabId: string
    logs: ParsedLogMessage[]
    orderBy: LogsOrderBy
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

        // Cursor (vim-style navigation position)
        setCursorIndex: (index: number | null) => ({ index }),
        userSetCursorIndex: (index: number | null) => ({ index }), // User-initiated (click)
        resetCursor: true,
        moveCursorDown: (logsLength: number) => ({ logsLength }),
        moveCursorUp: (logsLength: number) => ({ logsLength }),

        // Expansion
        toggleExpandLog: (logId: string) => ({ logId }),

        // Deep linking - position cursor at a specific log by ID
        setLinkToLogId: (linkToLogId: string | null) => ({ linkToLogId }),
        setCursorToLogId: (logId: string, logs: ParsedLogMessage[]) => ({ logId, logs }),

        // Copy link to log
        copyLinkToLog: (logId: string) => ({ logId }),

        // Sync logs from props
        setLogs: (logs: ParsedLogMessage[]) => ({ logs }),
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

        cursorIndex: [
            null as number | null,
            { persist: true },
            {
                setCursorIndex: (_, { index }) => index,
                userSetCursorIndex: (_, { index }) => index,
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
                userSetCursorIndex: () => null, // User clicked a row
            },
        ],
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.logs !== oldProps.logs) {
            actions.setLogs(props.logs)
        }
    }),

    selectors({
        pinnedLogsArray: [(s) => [s.pinnedLogs], (pinnedLogs): ParsedLogMessage[] => Object.values(pinnedLogs)],

        getCursorLogId: [
            (s) => [s.cursorIndex],
            (cursorIndex: number | null) =>
                (logs: ParsedLogMessage[]): string | null =>
                    cursorIndex !== null && cursorIndex >= 0 && cursorIndex < logs.length
                        ? logs[cursorIndex].uuid
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

    listeners(({ actions, values }) => ({
        moveCursorDown: ({ logsLength }) => {
            if (logsLength === 0) {
                return
            }

            if (values.cursorIndex === null) {
                actions.setCursorIndex(0)
                return
            }

            if (values.cursorIndex < logsLength - 1) {
                actions.setCursorIndex(values.cursorIndex + 1)
            }
        },
        moveCursorUp: ({ logsLength }) => {
            if (logsLength === 0) {
                return
            }

            if (values.cursorIndex === null) {
                actions.setCursorIndex(logsLength - 1)
                return
            }

            if (values.cursorIndex > 0) {
                actions.setCursorIndex(values.cursorIndex - 1)
            }
        },
        setCursorToLogId: ({ logId, logs }) => {
            const index = logs.findIndex((log) => log.uuid === logId)
            if (index !== -1) {
                actions.setCursorIndex(index)
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
        }
    }),
])
