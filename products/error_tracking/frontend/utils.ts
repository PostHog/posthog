import equal from 'fast-deep-equal'
import { LogicWrapper } from 'kea'
import { routerType } from 'kea-router/lib/routerType'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { Dayjs, dayjs, QUnitType } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, isStringDateRegex } from 'lib/utils'
import { MouseEvent } from 'react'
import { Params } from 'scenes/sceneTypes'

import { DateRange, ErrorTrackingIssue } from '~/queries/schema/schema-general'

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

const volumePeriods: 'volumeRange'[] = ['volumeRange']
const sumVolumes = (...arrays: number[][]): number[] =>
    arrays[0].map((_, i) => arrays.reduce((sum, arr) => sum + arr[i], 0))

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

        volumePeriods.forEach((period) => {
            const volume = aggregations[period]
            if (volume) {
                const mergingVolumes: number[][] = mergingIssues
                    .map((issue) => (issue.aggregations ? issue.aggregations[period] : undefined))
                    .filter((volume) => volume != undefined) as number[][]
                aggregations[period] = sumVolumes(...mergingVolumes, volume)
            }
        })

        aggregations.users = sum('users')
        aggregations.sessions = sum('sessions')
        aggregations.occurrences = sum('occurrences')
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

export function generateSparklineLabels(range: DateRange, resolution: number): Dayjs[] {
    const { date_from, date_to } = ResolvedDateRange.fromDateRange(range)
    const bin_size = Math.floor(date_to.diff(date_from, 'milliseconds') / resolution)
    const labels = Array.from({ length: resolution }, (_, i) => {
        return date_from.add(i * bin_size, 'milliseconds')
    })
    return labels
}

export type DateRangePrecision = { unit: QUnitType; value: number }

export class ResolvedDateRange {
    date_from: Dayjs
    date_to: Dayjs

    constructor(date_from: Dayjs, date_to: Dayjs) {
        this.date_from = date_from
        this.date_to = date_to
    }

    toDateRange(): DateRange {
        return {
            date_from: this.date_from.toISOString(),
            date_to: this.date_to.toISOString(),
        }
    }

    static fromDateRange(dateRange: DateRange, precision?: DateRangePrecision): ResolvedDateRange {
        const fromOffset = precision
            ? dayjs().subtract(precision.value, precision.unit).startOf(precision.unit)
            : dayjs()
        const toOffset = precision ? dayjs().add(precision.value, precision.unit).endOf(precision.unit) : dayjs()
        return new ResolvedDateRange(
            resolveDate(fromOffset, dateRange.date_from),
            resolveDate(toOffset, dateRange.date_to)
        )
    }
}

// Converts relative date range to absolute date range
export function resolveDateRange(dateRange: DateRange, precision?: DateRangePrecision): ResolvedDateRange {
    return ResolvedDateRange.fromDateRange(dateRange, precision)
}

// Converts relative date to absolute date.
export function resolveDate(offset: Dayjs, date?: string | null): Dayjs {
    if (!date) {
        return offset
    }
    if (date == 'all') {
        return offset.subtract(1, 'year')
    }
    const parsedDate = datetimeStringToDayJs(date, offset)
    if (parsedDate) {
        return parsedDate
    }
    throw new Error(`Invalid date: ${date}`)
}

const customOptions: Record<string, string> = {
    dStart: 'Today', // today
    mStart: 'Month',
    yStart: 'Year',
    all: 'All',
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
