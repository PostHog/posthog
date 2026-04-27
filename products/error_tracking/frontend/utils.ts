import equal from 'fast-deep-equal'
import { LogicWrapper } from 'kea'
import { routerType } from 'kea-router/lib/routerType'
import { MouseEvent } from 'react'

import { ErrorTrackingException, ErrorTrackingStackFrame } from 'lib/components/Errors/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs, isStringDateRegex } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { DateRange, ErrorTrackingIssue } from '~/queries/schema/schema-general'

export const ERROR_TRACKING_LOGIC_KEY = 'errorTracking'
export const ERROR_TRACKING_LISTING_RESOLUTION = 20
export const ERROR_TRACKING_DETAILS_RESOLUTION = 50

// Cross-origin script tags swallow their stack trace and surface as the literal "Script error."
// (with or without the trailing period depending on the browser).
const THIRD_PARTY_SCRIPT_ERROR_VALUES: ReadonlySet<string> = new Set(['Script error.', 'Script error'])

const EXTENSION_FRAME_SCHEMES = [
    'chrome-extension://',
    'moz-extension://',
    'safari-extension://',
    'safari-web-extension://',
] as const

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

export function isThirdPartyScriptError(value: ErrorTrackingException['value'] | undefined | null): boolean {
    if (typeof value !== 'string') {
        return false
    }
    return THIRD_PARTY_SCRIPT_ERROR_VALUES.has(value.trim())
}

/**
 * Frames sourced from a browser extension (chrome-extension://, moz-extension://, ...).
 * These almost never represent issues an application owner can fix, so we treat them as noise.
 */
export function isExtensionFrame(frame: Pick<ErrorTrackingStackFrame, 'source'> | null | undefined): boolean {
    const source = frame?.source
    if (typeof source !== 'string') {
        return false
    }
    return EXTENSION_FRAME_SCHEMES.some((scheme) => source.startsWith(scheme))
}

/**
 * Returns true if the source path looks like a browser extension URL.
 * Use when only the raw source string is available (e.g. an issue list row).
 */
export function isExtensionSource(source: string | null | undefined): boolean {
    if (typeof source !== 'string') {
        return false
    }
    return EXTENSION_FRAME_SCHEMES.some((scheme) => source.startsWith(scheme))
}

/**
 * Heuristic for issue-level "this is almost certainly third-party noise" flagging.
 * Returns the human-readable reason when the issue is likely noise, or null otherwise.
 *
 * Used to de-prioritise noise in the issue list and AI tool output rather than
 * presenting cross-origin / extension errors as equal-weight to actionable issues.
 */
export function getThirdPartyNoiseReason(issue: {
    description?: string | null
    name?: string | null
    source?: string | null
}): string | null {
    if (isThirdPartyScriptError(issue.description) || isThirdPartyScriptError(issue.name)) {
        return 'Cross-origin "Script error." with no usable stack frames'
    }
    if (isExtensionSource(issue.source)) {
        return 'Top frame is from a browser extension'
    }
    return null
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
