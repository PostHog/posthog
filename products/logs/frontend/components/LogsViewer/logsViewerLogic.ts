import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import Papa from 'papaparse'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { AttributeColumnConfig, LogsOrderBy, ParsedLogMessage } from '../../types'
import { logDetailsModalLogic } from './LogDetailsModal/logDetailsModalLogic'
import type { logsViewerLogicType } from './logsViewerLogicType'
import { logsViewerSettingsLogic } from './logsViewerSettingsLogic'

// Helper to get next order value for a new column
const getNextOrder = (config: Record<string, AttributeColumnConfig>): number => {
    const orders = Object.values(config).map((c) => c.order)
    return orders.length > 0 ? Math.max(...orders) + 1 : 0
}

export interface VisibleLogsTimeRange {
    date_from: string
    date_to: string
}

export type LogCursor = number | null

export interface LogsViewerLogicProps {
    tabId: string
    logs: ParsedLogMessage[]
    orderBy: LogsOrderBy
    onAddFilter?: (key: string, value: string, operator?: PropertyOperator, type?: PropertyFilterType) => void
}

export const logsViewerLogic = kea<logsViewerLogicType>([
    path((tabId) => ['products', 'logs', 'frontend', 'components', 'LogsViewer', 'logsViewerLogic', tabId]),
    props({} as LogsViewerLogicProps),
    key((props) => props.tabId),
    connect(() => ({
        values: [
            logsViewerSettingsLogic,
            ['timezone', 'wrapBody', 'prettifyJson'],
            logDetailsModalLogic,
            ['isLogDetailsOpen'],
        ],
        actions: [
            logsViewerSettingsLogic,
            ['setTimezone', 'setWrapBody', 'setPrettifyJson'],
            logDetailsModalLogic,
            ['openLogDetails', 'closeLogDetails'],
        ],
    })),

    actions({
        // Pinning
        togglePinLog: (log: ParsedLogMessage) => ({ log }),

        // Focus (for keyboard shortcuts)
        setFocused: (isFocused: boolean) => ({ isFocused }),

        // Cursor (vim-style navigation position)
        setCursor: (cursor: LogCursor) => ({ cursor }),
        setCursorIndex: (index: number | null) => ({ index }),
        userSetCursorIndex: (index: number | null) => ({ index }), // User-initiated (click on row)
        resetCursor: true,
        moveCursorDown: (shiftSelect?: boolean) => ({ shiftSelect: shiftSelect ?? false }),
        moveCursorUp: (shiftSelect?: boolean) => ({ shiftSelect: shiftSelect ?? false }),
        requestScrollToCursor: true, // Signals React to scroll to current cursor position

        // Deep linking - position cursor at a specific log by ID
        setLinkToLogId: (linkToLogId: string | null) => ({ linkToLogId }),
        setCursorToLogId: (logId: string) => ({ logId }),

        // Copy link to log
        copyLinkToLog: (logId: string) => ({ logId }),

        // Sync logs from props
        setLogs: (logs: ParsedLogMessage[]) => ({ logs }),

        // Filter actions (emits to parent via props callback)
        addFilter: (key: string, value: string, operator?: PropertyOperator, type?: PropertyFilterType) => ({
            key,
            value,
            operator,
            type,
        }),

        // Attribute breakdowns (per-log)
        toggleAttributeBreakdown: (logId: string, attributeKey: string) => ({ logId, attributeKey }),

        // Attribute columns (show attributes as columns in the log list)
        toggleAttributeColumn: (attributeKey: string) => ({ attributeKey }),
        removeAttributeColumn: (attributeKey: string) => ({ attributeKey }),
        setAttributeColumnWidth: (attributeKey: string, width: number) => ({ attributeKey, width }),
        moveAttributeColumn: (attributeKey: string, direction: 'left' | 'right') => ({ attributeKey, direction }),

        // Row height recomputation (triggered by child components when content changes)
        recomputeRowHeights: (logIds?: string[]) => ({ logIds }),

        // Multi-select
        toggleSelectLog: (logId: string) => ({ logId }),
        setSelectedLogIds: (selectedLogIds: Record<string, boolean>) => ({ selectedLogIds }),
        selectLogRange: (fromIndex: number, toIndex: number) => ({ fromIndex, toIndex }),
        selectAll: (logsToSelect?: ParsedLogMessage[]) => ({ logsToSelect }),
        clearSelection: true,
        copySelectedLogs: true,
        exportSelectedAsJson: true,
        exportSelectedAsCsv: true,

        // Per-row prettify
        togglePrettifyLog: (logId: string) => ({ logId }),
    }),

    reducers(({ props }) => ({
        // Synced from props via propsChanged
        logs: [props.logs, { setLogs: (_, { logs }) => logs }],

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
            null as LogCursor,
            { persist: true },
            {
                setCursor: (_, { cursor }) => cursor,
                setCursorIndex: (_, { index }) => index,
                userSetCursorIndex: (_, { index }) => index,
                resetCursor: () => null,
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

        // Attribute columns config (order, width, etc.)
        attributeColumnsConfig: [
            {} as Record<string, AttributeColumnConfig>,
            { persist: true },
            {
                toggleAttributeColumn: (state, { attributeKey }) => {
                    if (attributeKey in state) {
                        const { [attributeKey]: _, ...rest } = state
                        return rest
                    }
                    return { ...state, [attributeKey]: { order: getNextOrder(state) } }
                },
                removeAttributeColumn: (state, { attributeKey }) => {
                    const { [attributeKey]: _, ...rest } = state
                    return rest
                },
                setAttributeColumnWidth: (state, { attributeKey, width }) => {
                    if (!(attributeKey in state)) {
                        return state
                    }
                    return { ...state, [attributeKey]: { ...state[attributeKey], width } }
                },
                moveAttributeColumn: (state, { attributeKey, direction }) => {
                    if (!(attributeKey in state)) {
                        return state
                    }
                    const entries = Object.entries(state) as [string, AttributeColumnConfig][]
                    const sorted = entries.sort(([, a], [, b]) => a.order - b.order)
                    const index = sorted.findIndex(([key]) => key === attributeKey)
                    const targetIndex = direction === 'left' ? index - 1 : index + 1
                    if (targetIndex < 0 || targetIndex >= sorted.length) {
                        return state
                    }
                    // Swap orders
                    const [targetKey] = sorted[targetIndex]
                    return {
                        ...state,
                        [attributeKey]: { ...state[attributeKey], order: state[targetKey].order },
                        [targetKey]: { ...state[targetKey], order: state[attributeKey].order },
                    }
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

        // Tracks requests to scroll to cursor - VirtualizedLogsList watches this timestamp
        scrollToCursorRequest: [
            0,
            {
                requestScrollToCursor: () => Date.now(),
            },
        ],

        // Multi-select state
        selectedLogIds: [
            {} as Record<string, boolean>,
            {
                toggleSelectLog: (state, { logId }) => {
                    if (state[logId]) {
                        const { [logId]: _, ...rest } = state
                        return rest
                    }
                    return { ...state, [logId]: true }
                },
                setSelectedLogIds: (_, { selectedLogIds }) => selectedLogIds,
                clearSelection: () => ({}),
                setLogs: () => ({}), // Clear selection when logs change
            },
        ],

        prettifiedLogIds: [
            new Set<string>(),
            {
                togglePrettifyLog: (state, { logId }) => {
                    const next = new Set(state)
                    if (next.has(logId)) {
                        next.delete(logId)
                    } else {
                        next.add(logId)
                    }
                    return next
                },
                setLogs: () => new Set<string>(),
            },
        ],
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.logs !== oldProps.logs) {
            actions.setLogs(props.logs)
            actions.recomputeRowHeights()
        }
    }),

    selectors({
        tabId: [(_, p) => [p.tabId], (tabId: string): string => tabId],

        pinnedLogsArray: [(s) => [s.pinnedLogs], (pinnedLogs): ParsedLogMessage[] => Object.values(pinnedLogs)],

        // Convenience selectors for cursor components
        cursorIndex: [(s) => [s.cursor], (cursor): number | null => cursor],

        cursorLogId: [
            (s) => [s.cursor, s.logs],
            (cursor: LogCursor, logs: ParsedLogMessage[]): string | null =>
                cursor !== null && cursor >= 0 && cursor < logs.length ? logs[cursor].uuid : null,
        ],

        // Keyboard nav enabled when focused OR log details is open (so j/k still work while viewing details)
        keyboardNavEnabled: [
            (s) => [s.isFocused, s.isLogDetailsOpen],
            (isFocused: boolean, isLogDetailsOpen: boolean): boolean => isFocused || isLogDetailsOpen,
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
                        date_to: dayjs(firstTimestamp).add(1, 'millisecond').toISOString(),
                    }
                }
                return {
                    date_from: dayjs(firstTimestamp).toISOString(),
                    date_to: dayjs(lastTimestamp).add(1, 'millisecond').toISOString(),
                }
            },
        ],

        logsCount: [(s) => [s.logs], (logs: ParsedLogMessage[]): number => logs.length],

        // Derived: ordered array of attribute column keys
        attributeColumns: [
            (s) => [s.attributeColumnsConfig],
            (config: Record<string, AttributeColumnConfig>): string[] =>
                Object.entries(config)
                    .sort(([, a], [, b]) => a.order - b.order)
                    .map(([key]) => key),
        ],

        // Derived: width lookup for attribute columns
        attributeColumnWidths: [
            (s) => [s.attributeColumnsConfig],
            (config: Record<string, AttributeColumnConfig>): Record<string, number> =>
                Object.fromEntries(
                    Object.entries(config)
                        .filter(([, c]) => c.width !== undefined)
                        .map(([key, c]) => [key, c.width as number])
                ),
        ],

        isAttributeColumn: [
            (s) => [s.attributeColumnsConfig],
            (config: Record<string, AttributeColumnConfig>) =>
                (attributeKey: string): boolean =>
                    attributeKey in config,
        ],

        // Selection selectors
        isSelectionActive: [
            (s) => [s.selectedLogIds],
            (selectedLogIds): boolean => Object.keys(selectedLogIds).length > 0,
        ],
        selectedCount: [(s) => [s.selectedLogIds], (selectedLogIds): number => Object.keys(selectedLogIds).length],
        selectedLogsArray: [
            (s) => [s.selectedLogIds, s.logs],
            (selectedLogIds, logs): ParsedLogMessage[] => logs.filter((log) => selectedLogIds[log.uuid]),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        setLogs: ({ logs }) => {
            if (logs.length === 0) {
                actions.resetCursor()
            }
        },
        addFilter: ({ key, value, operator, type }) => {
            props.onAddFilter?.(key, value, operator, type)
        },
        togglePinLog: ({ log }) => {
            if (values.pinnedLogs[log.uuid]) {
                posthog.capture('logs log pinned')
            }
        },
        toggleSelectLog: ({ logId }) => {
            if (values.selectedLogIds[logId]) {
                posthog.capture('logs log selected')
            } else {
                posthog.capture('logs log unselected')
            }
        },
        clearSelection: () => {
            posthog.capture('logs clear selection', { count: values.selectedCount })
        },
        closeLogDetails: () => {
            // Restore focus to logs viewer when modal closes
            actions.setFocused(true)
        },
        togglePrettifyLog: ({ logId }) => {
            actions.recomputeRowHeights([logId])
        },
        moveCursorDown: ({ shiftSelect }) => {
            const { logs, cursor } = values
            if (logs.length === 0) {
                return
            }

            if (cursor === null) {
                actions.setCursor(0)
                if (shiftSelect && logs[0]) {
                    actions.setSelectedLogIds({ ...values.selectedLogIds, [logs[0].uuid]: true })
                }
                return
            }

            if (cursor < logs.length - 1) {
                const newIndex = cursor + 1
                actions.setCursor(newIndex)
                if (shiftSelect && logs[newIndex]) {
                    actions.setSelectedLogIds({ ...values.selectedLogIds, [logs[newIndex].uuid]: true })
                }
            }
        },
        moveCursorUp: ({ shiftSelect }) => {
            const { logs, cursor } = values
            if (logs.length === 0) {
                return
            }

            if (cursor === null) {
                const lastIndex = logs.length - 1
                actions.setCursor(lastIndex)
                if (shiftSelect && logs[lastIndex]) {
                    actions.setSelectedLogIds({ ...values.selectedLogIds, [logs[lastIndex].uuid]: true })
                }
                return
            }

            if (cursor > 0) {
                const newIndex = cursor - 1
                actions.setCursor(newIndex)
                if (shiftSelect && logs[newIndex]) {
                    actions.setSelectedLogIds({ ...values.selectedLogIds, [logs[newIndex].uuid]: true })
                }
            }
        },
        setCursorToLogId: ({ logId }) => {
            const index = values.logs.findIndex((log) => log.uuid === logId)
            if (index !== -1) {
                actions.setCursor(index)
                // If navigating via link, also open the details modal
                if (values.linkToLogId === logId) {
                    actions.openLogDetails(values.logs[index])
                }
            }
        },
        copyLinkToLog: ({ logId }) => {
            posthog.capture('logs link copied')
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
        copySelectedLogs: () => {
            const selectedLogs = values.selectedLogsArray
            posthog.capture('logs bulk copy', { count: selectedLogs.length })
            const text = selectedLogs.map((log) => log.body).join('\n')
            void copyToClipboard(text, `${selectedLogs.length} log message${selectedLogs.length === 1 ? '' : 's'}`)
        },
        selectLogRange: ({ fromIndex, toIndex }) => {
            posthog.capture('logs range selected', { count: Math.abs(toIndex - fromIndex) + 1 })
            const minIndex = Math.min(fromIndex, toIndex)
            const maxIndex = Math.max(fromIndex, toIndex)
            const newSelection: Record<string, boolean> = { ...values.selectedLogIds }
            for (let i = minIndex; i <= maxIndex; i++) {
                const log = values.logs[i]
                if (log) {
                    newSelection[log.uuid] = true
                }
            }
            actions.setSelectedLogIds(newSelection)
        },
        selectAll: ({ logsToSelect }) => {
            const logs = logsToSelect ?? values.logs
            posthog.capture('logs select all', { count: logs.length })
            const newSelection: Record<string, boolean> = {}
            for (const log of logs) {
                newSelection[log.uuid] = true
            }
            actions.setSelectedLogIds(newSelection)
        },
        exportSelectedAsJson: () => {
            const selectedLogs = values.selectedLogsArray.map((log) => ({
                timestamp: log.timestamp,
                observed_timestamp: log.observed_timestamp,
                severity_text: log.severity_text,
                body: log.body,
                attributes: log.attributes,
                resource_attributes: log.resource_attributes,
                trace_id: log.trace_id,
                span_id: log.span_id,
            }))
            posthog.capture('logs exported', { format: 'json', count: selectedLogs.length })
            const json = JSON.stringify(selectedLogs, null, 2)
            const blob = new Blob([json], { type: 'application/json' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `logs-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`
            a.click()
            setTimeout(() => URL.revokeObjectURL(url), 0)
        },
        exportSelectedAsCsv: () => {
            const selectedLogs = values.selectedLogsArray
            posthog.capture('logs exported', { format: 'csv', count: selectedLogs.length })
            const headers = ['timestamp', 'severity', ...values.attributeColumns, 'body']
            const rows = selectedLogs.map((log) => [
                log.timestamp,
                log.severity_text,
                ...values.attributeColumns.map((col) => log.attributes[col] ?? log.resource_attributes[col] ?? ''),
                log.body,
            ])
            const csv = Papa.unparse([headers, ...rows])
            const blob = new Blob([csv], { type: 'text/csv' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `logs-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.csv`
            a.click()
            setTimeout(() => URL.revokeObjectURL(url), 0)
        },
        toggleAttributeColumn: ({ attributeKey }) => {
            if (attributeKey in values.attributeColumnsConfig) {
                posthog.capture('logs column added', { attribute_key: attributeKey })
            }
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

    subscriptions(({ actions }) => ({
        cursorIndex: (cursorIndex) => {
            if (cursorIndex !== null) {
                actions.requestScrollToCursor()
            }
        },
    })),
])
