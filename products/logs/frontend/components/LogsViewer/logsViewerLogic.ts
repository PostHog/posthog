import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import type { logsViewerLogicType } from './logsViewerLogicType'

export interface LogsViewerLogicProps {
    tabId: string
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
        resetCursor: true,
        moveCursorDown: (logsLength: number) => ({ logsLength }),
        moveCursorUp: (logsLength: number) => ({ logsLength }),

        // Expansion
        toggleExpandLog: (logId: string) => ({ logId }),
    }),

    reducers({
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
    })),
])
