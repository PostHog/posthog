import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ErrorEventType } from 'lib/components/Errors/types'
import { getSessionId, getTraceId } from 'lib/components/Errors/utils'
import { usableId } from 'lib/components/ViewTraceButton/usableId'
import { dayjs } from 'lib/dayjs'

import { DateRange, QueryLogTags } from '~/queries/schema/schema-general'

import { EXCEPTION_LOGS_WINDOW_MINUTES } from 'products/logs/frontend/utils'

import type { LinkedDataKind } from '../../components/ExceptionCard/exceptionCardLogic'
import {
    ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY,
    issueFiltersLogic,
} from '../../components/IssueFilters/issueFiltersLogic'
import {
    errorTrackingIssueCorrelationIdsQuery,
    errorTrackingLinkedDataWhere,
    errorTrackingLinkedLogsQuery,
    errorTrackingLinkedRecordingsQuery,
} from '../../queries'

export interface IssueLinkedDataLogicProps {
    issueId: string
}

export interface LinkedLogsData {
    exceptionCount: number
    sessionIds: string[]
    traceIds: string[]
}

export interface LinkedRecordingData {
    exceptionCount: number
    sessionIds: string[]
}

export interface IssueLinkedData {
    exceptionCount: number
    logs: LinkedLogsData
    recording: LinkedRecordingData
}

export interface EventLinkedData {
    logs: boolean
    recording: boolean
}

type CorrelationIdsRow = [
    sessionId: string | null,
    traceId: string | null,
    exceptionCount: number,
    firstSeen: string,
    lastSeen: string,
]

const QUERY_TAGS: QueryLogTags = { productKey: 'error_tracking', scene: 'ErrorTrackingIssue' }

const EMPTY_LINKED_DATA: IssueLinkedData = {
    exceptionCount: 0,
    logs: { exceptionCount: 0, sessionIds: [], traceIds: [] },
    recording: { exceptionCount: 0, sessionIds: [] },
}

function uniqueStrings(values: (string | null | undefined)[]): string[] {
    return [...new Set(values.filter((value): value is string => !!value))]
}

// Exceptions carry trace IDs as hex, and the logs table stores the raw bytes as base64.
function hexToBase64(hex: string): string {
    const bytes = hex.match(/../g) ?? []
    return btoa(String.fromCharCode(...bytes.map((byte) => parseInt(byte, 16))))
}

// The linked data is supplementary, so a failed lookup counts as "nothing linked" instead of
// blocking the issue page. A team without logs, for example, fails the logs query.
async function queryResultsOrEmpty<T>(query: () => Promise<{ results: T[] }>): Promise<T[]> {
    try {
        return (await query()).results
    } catch (error) {
        console.error('Failed to load linked data for the issue:', error)
        return []
    }
}

export async function loadIssueLinkedData(
    issueId: string,
    dateRange: DateRange,
    filterTestAccounts: boolean
): Promise<IssueLinkedData> {
    const rows = await queryResultsOrEmpty<CorrelationIdsRow>(() =>
        api.queryHogQL<CorrelationIdsRow[]>(errorTrackingIssueCorrelationIdsQuery(issueId), QUERY_TAGS, {
            queryParams: { filters: { dateRange, filterTestAccounts } },
        })
    )
    if (rows.length === 0) {
        return EMPTY_LINKED_DATA
    }

    const sessionIds = uniqueStrings(rows.map(([sessionId]) => sessionId))
    // An all-zeros trace ID means "no trace", and uninstrumented logs carry it too.
    const traceIds = uniqueStrings(rows.map(([, traceId]) => (usableId(traceId) ? traceId : null)))
    const firstSeen = Math.min(...rows.map(([, , , firstSeen]) => dayjs(firstSeen).valueOf()))
    const lastSeen = Math.max(...rows.map(([, , , , lastSeen]) => dayjs(lastSeen).valueOf()))
    const dateFrom = dayjs(firstSeen).subtract(EXCEPTION_LOGS_WINDOW_MINUTES, 'minute').toISOString()
    const dateTo = dayjs(lastSeen).add(EXCEPTION_LOGS_WINDOW_MINUTES, 'minute').toISOString()

    const [logRows, recordingRows] = await Promise.all([
        sessionIds.length > 0 || traceIds.length > 0
            ? queryResultsOrEmpty<[traceId: string, sessionId: string | null]>(() =>
                  api.queryHogQL(
                      errorTrackingLinkedLogsQuery({
                          sessionIds,
                          base64TraceIds: traceIds.map(hexToBase64),
                          dateFrom,
                          dateTo,
                      }),
                      QUERY_TAGS
                  )
              )
            : [],
        sessionIds.length > 0
            ? queryResultsOrEmpty<[sessionId: string]>(() =>
                  api.queryHogQL(errorTrackingLinkedRecordingsQuery({ sessionIds, dateFrom, dateTo }), QUERY_TAGS)
              )
            : [],
    ])

    const foundLogTraceIds = new Set(logRows.map(([traceId]) => traceId))
    const foundLogSessionIds = new Set(logRows.map(([, sessionId]) => sessionId))
    const foundRecordingSessionIds = new Set(recordingRows.map(([sessionId]) => sessionId))
    // A log row matched by its session also carries a trace ID, which can be the all-zeros sentinel.
    // Keep only the usable IDs the exceptions carry, so that sentinel links no exception.
    const logTraceIds = new Set(traceIds.filter((traceId) => foundLogTraceIds.has(hexToBase64(traceId))))
    const logSessionIds = new Set(sessionIds.filter((sessionId) => foundLogSessionIds.has(sessionId)))
    const recordingSessionIds = new Set(sessionIds.filter((sessionId) => foundRecordingSessionIds.has(sessionId)))

    const linkedData: IssueLinkedData = {
        exceptionCount: 0,
        logs: { exceptionCount: 0, sessionIds: [...logSessionIds], traceIds: [...logTraceIds] },
        recording: { exceptionCount: 0, sessionIds: [...recordingSessionIds] },
    }
    for (const [sessionId, traceId, exceptionCount] of rows) {
        linkedData.exceptionCount += exceptionCount
        if ((sessionId && logSessionIds.has(sessionId)) || (traceId && logTraceIds.has(traceId))) {
            linkedData.logs.exceptionCount += exceptionCount
        }
        if (sessionId && recordingSessionIds.has(sessionId)) {
            linkedData.recording.exceptionCount += exceptionCount
        }
    }
    return linkedData
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface issueLinkedDataLogicValues {
    dateRange: DateRange // issueFiltersLogic
    filterTestAccounts: boolean // issueFiltersLogic
    getEventLinkedData: (event: ErrorEventType | null | undefined) => EventLinkedData | null
    linkedData: IssueLinkedData | null
    linkedDataLoading: boolean
    linkedDataPending: boolean
    linkedDataRequested: boolean
    linkedDataWhere: string[]
    requiredLinks: LinkedDataKind[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface issueLinkedDataLogicActions {
    clearRequiredLinks: () => {
        value: true
    }
    loadLinkedData: () => any
    loadLinkedDataFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadLinkedDataSuccess: (
        linkedData: IssueLinkedData | null,
        payload?: any
    ) => {
        linkedData: IssueLinkedData | null
        payload?: any
    }
    requestLinkedData: () => {
        value: true
    }
    setDateRange: (
        dateRange: DateRange,
        fromPreview?: boolean
    ) => {
        dateRange: DateRange
        fromPreview: boolean
    } // issueFiltersLogic
    setFilterTestAccounts: (filterTestAccounts: boolean) => {
        filterTestAccounts: boolean
    } // issueFiltersLogic
    setLinkRequired: (
        kind: LinkedDataKind,
        required: boolean
    ) => {
        kind: LinkedDataKind
        required: boolean
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface issueLinkedDataLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        linkedDataPending: (requiredLinks: LinkedDataKind[], linkedData: IssueLinkedData | null) => boolean
        linkedDataWhere: (requiredLinks: LinkedDataKind[], linkedData: IssueLinkedData | null) => string[]
        getEventLinkedData: (
            linkedData: IssueLinkedData | null
        ) => (event: ErrorEventType | null | undefined) => EventLinkedData | null
    }
}

export type issueLinkedDataLogicType = MakeLogicType<
    issueLinkedDataLogicValues,
    issueLinkedDataLogicActions,
    IssueLinkedDataLogicProps,
    issueLinkedDataLogicMeta
>

/**
 * Finds which of an issue's exceptions have linked logs or a session recording, and filters the
 * issue's events list down to them. The scene logic connects this one for its events query, so
 * the lookup only runs once the issue page asks for it with `requestLinkedData`.
 */
export const issueLinkedDataLogic = kea<issueLinkedDataLogicType>([
    path((key) => ['products', 'error_tracking', 'scenes', 'ErrorTrackingIssueScene', 'issueLinkedDataLogic', key]),
    props({} as IssueLinkedDataLogicProps),
    key((props) => props.issueId),

    connect(() => ({
        values: [
            issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }),
            ['dateRange', 'filterTestAccounts'],
        ],
        actions: [
            issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }),
            ['setDateRange', 'setFilterTestAccounts'],
        ],
    })),

    actions({
        clearRequiredLinks: true,
        requestLinkedData: true,
        setLinkRequired: (kind: LinkedDataKind, required: boolean) => ({ kind, required }),
    }),

    loaders(({ props, values }) => ({
        linkedData: [
            null as IssueLinkedData | null,
            {
                loadLinkedData: async (_, breakpoint) => {
                    const linkedData = await loadIssueLinkedData(
                        props.issueId,
                        values.dateRange,
                        values.filterTestAccounts
                    )
                    breakpoint()
                    return linkedData
                },
            },
        ],
    })),

    reducers({
        // Cleared on reload, so the events list never filters by IDs from another date range.
        linkedData: {
            loadLinkedData: () => null,
        },
        linkedDataRequested: [
            false,
            {
                requestLinkedData: () => true,
                setLinkRequired: () => true,
            },
        ],
        requiredLinks: [
            [] as LinkedDataKind[],
            {
                setLinkRequired: (state, { kind, required }) => {
                    const withoutKind = state.filter((existing) => existing !== kind)
                    return required ? [...withoutKind, kind] : withoutKind
                },
                clearRequiredLinks: () => [],
            },
        ],
    }),

    selectors({
        linkedDataPending: [
            (s) => [s.requiredLinks, s.linkedData],
            (requiredLinks: LinkedDataKind[], linkedData: IssueLinkedData | null): boolean =>
                requiredLinks.length > 0 && linkedData === null,
        ],
        linkedDataWhere: [
            (s) => [s.requiredLinks, s.linkedData],
            (requiredLinks: LinkedDataKind[], linkedData: IssueLinkedData | null): string[] => {
                if (!linkedData) {
                    return []
                }
                return requiredLinks.map((kind) =>
                    kind === 'logs'
                        ? errorTrackingLinkedDataWhere(linkedData.logs)
                        : errorTrackingLinkedDataWhere(linkedData.recording)
                )
            },
        ],
        getEventLinkedData: [
            (s) => [s.linkedData],
            (linkedData: IssueLinkedData | null) =>
                (event: ErrorEventType | null | undefined): EventLinkedData | null => {
                    if (!linkedData || !event) {
                        return null
                    }
                    const sessionId = getSessionId(event.properties)
                    const traceId = getTraceId(event.properties)
                    return {
                        logs:
                            (!!sessionId && linkedData.logs.sessionIds.includes(sessionId)) ||
                            (!!traceId && linkedData.logs.traceIds.includes(traceId)),
                        recording: !!sessionId && linkedData.recording.sessionIds.includes(sessionId),
                    }
                },
        ],
    }),

    listeners(({ actions, values }) => {
        const reloadIfRequested = (): void => {
            if (values.linkedDataRequested) {
                actions.loadLinkedData()
            }
        }
        const loadIfMissing = (): void => {
            if (!values.linkedData && !values.linkedDataLoading) {
                actions.loadLinkedData()
            }
        }
        return {
            requestLinkedData: loadIfMissing,
            setLinkRequired: loadIfMissing,
            setDateRange: reloadIfRequested,
            setFilterTestAccounts: reloadIfRequested,
        }
    }),
])
