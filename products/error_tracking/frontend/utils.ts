import { deepEqual as equal } from 'fast-equals'
import { LogicWrapper } from 'kea'
import { routerType } from 'kea-router/lib/routerType'
import { MouseEvent } from 'react'

import { ErrorTrackingException } from 'lib/components/Errors/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs, isStringDateRegex } from 'lib/utils/dateFilters'
import { Params } from 'scenes/sceneTypes'
import { convertUniversalFiltersToRecordingsQuery } from 'scenes/session-recordings/filters/recordingsQueryConversions'

import { DateRange, ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { escapeHogQLString } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    FilterLogicalOperator,
    PropertyFilterType,
    type UniversalFiltersGroup,
} from '~/types'

import type { ScannerHandoffIntent } from 'products/replay_vision/frontend/replay_scanners/scannerHandoffIntent'

/** Reason error tracking write actions are disabled, or null when the user has editor access. */
export function errorTrackingEditAccessDisabledReason(): string | null {
    return getAccessControlDisabledReason(AccessControlResourceType.ErrorTracking, AccessControlLevel.Editor)
}

export const ERROR_TRACKING_LOGIC_KEY = 'errorTracking'
export const ERROR_TRACKING_LISTING_RESOLUTION = 20
export const ERROR_TRACKING_DETAILS_RESOLUTION = 50

const THIRD_PARTY_SCRIPT_ERROR = 'Script error.'

export const SEARCHABLE_EXCEPTION_PROPERTIES = [
    '$exception_types',
    '$exception_values',
    '$exception_sources',
    '$exception_functions',
]
export const INTERNAL_EXCEPTION_PROPERTY_KEYS = [
    '$exception_list',
    '$exception_fingerprint_record',
    '$exception_proposed_fingerprint',
    ...SEARCHABLE_EXCEPTION_PROPERTIES,
]

export const ISSUE_STATUS_OPTIONS: ErrorTrackingIssue['status'][] = ['active', 'resolved', 'suppressed']

const sumVolumeBuckets = (
    primaryIssue: { label: string; value: number }[] | undefined,
    mergingIssues: ({ label: string; value: number }[] | undefined)[]
): { label: string; value: number }[] | undefined => {
    if (!primaryIssue) {
        return undefined
    }
    return primaryIssue.map((item, i) =>
        mergingIssues.reduce(
            (agg, arr) => {
                if (!arr) {
                    return agg
                }
                const value = arr[i]?.value || 0
                return {
                    label: arr[i]?.label || '',
                    value: agg.value + value,
                }
            },
            { label: item.label || '', value: item.value }
        )
    )
}

export const mergeIssues = (
    primaryIssue: ErrorTrackingIssue,
    mergingIssues: ErrorTrackingIssue[]
): ErrorTrackingIssue => {
    const [firstSeen, lastSeen] = mergingIssues.reduce(
        (res, g) => {
            const firstSeen = dayjs(g.first_seen)
            const lastSeen = dayjs(g.last_seen)
            return [res[0].isAfter(firstSeen) ? firstSeen : res[0], res[1].isBefore(lastSeen) ? lastSeen : res[1]]
        },
        [dayjs(primaryIssue.first_seen), dayjs(primaryIssue.last_seen)]
    )

    const aggregations = primaryIssue.aggregations

    if (aggregations) {
        const sum = (value: 'occurrences' | 'users' | 'sessions'): number => {
            return mergingIssues.reduce((sum, g) => sum + (g.aggregations?.[value] || 0), aggregations[value])
        }

        aggregations.users = sum('users')
        aggregations.sessions = sum('sessions')
        aggregations.occurrences = sum('occurrences')
        aggregations.volume_buckets =
            sumVolumeBuckets(
                primaryIssue.aggregations?.volume_buckets,
                mergingIssues.map((issue) => issue.aggregations?.volume_buckets)
            ) || []
    }

    return {
        ...primaryIssue,
        aggregations,
        first_seen: firstSeen.toISOString(),
        last_seen: lastSeen.toISOString(),
    }
}

export function isThirdPartyScriptError(value: ErrorTrackingException['value']): boolean {
    return value === THIRD_PARTY_SCRIPT_ERROR
}

// Recordings match on session start time, so pad past first_seen to catch a session that began
// before the exception fired, and past last_seen so a single-occurrence issue isn't a zero-width window.
// The selected event keeps the range valid when the user clicks before the last_seen query finishes.
export function getIssueReplayDateRange(
    firstSeen: string | null | undefined,
    lastSeen: Dayjs | null,
    selectedEventTimestamp?: string | null
): DateRange {
    const firstSeenAt = dayjs(firstSeen)
    const selectedEventSeenAt = selectedEventTimestamp ? dayjs(selectedEventTimestamp) : null
    // first_seen is annotated from fingerprint rows, so an issue with no ingested events
    // (reachable via the metrics error-spike overlay) has none — anchor on another known
    // timestamp instead of letting toISOString throw on an invalid date.
    const from = firstSeenAt.isValid()
        ? firstSeenAt
        : ([lastSeen, selectedEventSeenAt].find((d): d is Dayjs => !!d?.isValid()) ?? dayjs())
    const latestKnownSeenAt =
        selectedEventSeenAt?.isValid() && (!lastSeen || selectedEventSeenAt.isAfter(lastSeen))
            ? selectedEventSeenAt
            : lastSeen
    const to = latestKnownSeenAt?.isAfter(from) ? latestKnownSeenAt : from

    return {
        date_from: from.subtract(1, 'hour').toISOString(),
        date_to: to.add(1, 'hour').toISOString(),
    }
}

export function getIssueReplayFilterGroup(issueId: string): UniversalFiltersGroup {
    return {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        id: '$exception',
                        name: '$exception',
                        type: 'events',
                        properties: [
                            {
                                key: `issue_id = ${escapeHogQLString(issueId)}`,
                                type: PropertyFilterType.HogQL,
                            },
                        ],
                    },
                ],
            },
        ],
    }
}

function issueVisionScannerPrompt(issueName: string): string {
    return [
        `Watch each recording to understand what the user experienced around the error "${issueName}". For each session, describe:`,
        '- What the user was trying to do right before the error',
        '- What they saw when it happened: a broken screen, an error message, or nothing visible',
        '- How they reacted: retried, refreshed, rage-clicked, or left',
        '- Whether they recovered and finished, or gave up',
    ].join('\n')
}

/** The "scan this error's recordings" cross-sell: a Replay vision scanner prefilled to watch
 * sessions that hit this issue and summarize what users experienced around the error. */
export function issueVisionScannerHandoff(
    issueId: string,
    issueName: string,
    dateRange: DateRange
): ScannerHandoffIntent {
    return {
        source: 'error_tracking',
        scanner: {
            name: `Error tracking: ${issueName}`,
            description: 'Summarizes what users experienced in sessions that hit this error.',
            scanner_type: 'summarizer',
            scanner_config: { prompt: issueVisionScannerPrompt(issueName), length: 'medium' },
            // The date range rides along like the replay filters entry point's does; the backend
            // drops it on save because the scanner's schedule owns time.
            query: convertUniversalFiltersToRecordingsQuery({
                ...dateRange,
                duration: [],
                filter_group: getIssueReplayFilterGroup(issueId),
            }),
            // Error-scoped queries match few sessions, so scan them all rather than starting at
            // the wizard's narrow default rate.
            sampling_rate: 1.0,
            sampling_mode: 'balanced',
            // 5,000 credits is $50 (1 credit = $0.01), the anchor the goal-based flow suggests.
            credit_limit: 5000,
            credit_limit_enabled: true,
        },
    }
}

const customOptions: Record<string, string> = {
    dStart: 'Today', // today
    mStart: 'Month',
    yStart: 'Year',
    all: 'All',
}

export function dateRangeToIsoBounds(dateRange: DateRange | undefined): {
    dateFrom: string | undefined
    dateTo: string | undefined
} {
    if (!dateRange?.date_from) {
        return { dateFrom: undefined, dateTo: undefined }
    }
    const from = dateStringToDayJs(dateRange.date_from)
    const to = dateStringToDayJs(dateRange.date_to ?? new Date().toISOString())
    if (!from || !to) {
        return { dateFrom: undefined, dateTo: undefined }
    }
    return { dateFrom: from.toISOString(), dateTo: to.toISOString() }
}

export function generateDateRangeLabel(dateRange: DateRange): string | undefined {
    const dateFrom = dateRange.date_from
    if (!dateFrom) {
        return undefined
    }
    const isDateRelative = isStringDateRegex.test(dateFrom)
    if (dateFrom in customOptions) {
        return customOptions[dateFrom]
    } else if (isDateRelative) {
        return dateFrom?.replace('-', '')
    }
    return 'Custom'
}

export function datetimeStringToDayJs(date: string | null, offset: Dayjs): Dayjs | null {
    if (!isStringDateRegex.test(date || '')) {
        return dayjs(date)
    }
    const dateComponents = dateStringToComponents(date)
    if (!dateComponents) {
        return offset
    }
    return componentsToDayJs(dateComponents, offset)
}

export function syncSearchParams(
    router: LogicWrapper<routerType>,
    updateParams: (searchParams: Params) => Params
): [string, Params, Record<string, any>, { replace: boolean }] {
    let searchParams = { ...router.values.searchParams }
    searchParams = updateParams(searchParams)
    if (!equal(searchParams, router.values.searchParams)) {
        return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
    }
    return [router.values.location.pathname, router.values.searchParams, router.values.hashParams, { replace: false }]
}

export function updateSearchParams<T>(searchParams: Params, key: string, value: T, defaultValue: T): void {
    if (!equal(value, defaultValue)) {
        searchParams[key] = value
    } else {
        delete searchParams[key]
    }
}

export function cancelEvent(event: MouseEvent): void {
    event.preventDefault()
    event.stopPropagation()
}

export function sourceDisplay(source: string): string {
    const components = source.split('/')
    const fileComponent = components.pop()

    if (!fileComponent) {
        return ''
    }

    const fileWithoutExtension = fileComponent.split('.')[0]
    components.reverse()
    const index = components.findIndex((item) => /\./.test(item) || item === 'node_modules')
    const relevantComponents = index >= 0 ? components.slice(0, index) : components
    return [...relevantComponents.reverse(), fileWithoutExtension].join('.')
}
