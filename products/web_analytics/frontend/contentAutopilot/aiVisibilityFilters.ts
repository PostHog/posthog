import { dayjs } from 'lib/dayjs'
import { dateMapping } from 'lib/utils/dateFilters'
import { AI_VISIBILITY_URL_PARAMS } from 'scenes/web-analytics/common'

import type { DateMappingOption } from '~/types'

import { BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

export type AiVisibilityFilterTab = 'overview' | 'rankings' | 'prompts' | 'keywords'

export type AiVisibilityFilter = 'dateRange' | 'engine' | 'topic' | 'branded'

export const DEFAULT_AI_VISIBILITY_DATE_FROM = '-30d'
/** The longest range the API serves. "-90d" counts today too, so it has 91 days. */
export const MAX_AI_VISIBILITY_RANGE_DAYS = 91

// The checks run once a day, so hour ranges are left out. Week ranges are left out because the API does not
// read the project's week start, and ranges longer than the API serves are left out too.
const DATE_OPTION_KEYS = [
    'Custom',
    'Today',
    'Yesterday',
    'Last 7 days',
    'Last 14 days',
    'Last 30 days',
    'Last 90 days',
    'Last month',
    'This month',
]
export const AI_VISIBILITY_DATE_OPTIONS: DateMappingOption[] = dateMapping.filter((option) =>
    DATE_OPTION_KEYS.includes(option.key)
)

export interface AiVisibilityFilters {
    /** A date such as "2026-11-01" or a relative day such as "-30d", as the date filter writes it. */
    dateFrom: string
    /** The last day of the range, or null for today. */
    dateTo: string | null
    /** One answer engine id, or null for every engine. */
    engine: string | null
    /** One prompt topic, or null for every topic. An empty string is the prompts with no topic. */
    topic: string | null
    branded: BrandedSegmentEnumApi
}

/** The filters a tab honors. A filter a tab can't apply is left out of its bar rather than ignored. */
export const AI_VISIBILITY_TAB_FILTERS: Record<
    Exclude<AiVisibilityFilterTab, 'prompts'>,
    readonly AiVisibilityFilter[]
> = {
    overview: ['dateRange', 'engine', 'topic', 'branded'],
    rankings: ['dateRange', 'engine', 'topic', 'branded'],
    keywords: ['dateRange', 'engine', 'topic', 'branded'],
}

/** The prompts tab lists prompts, not answers, so the window and the engine only narrow the needs-improvement view. */
export const promptsTabFilters = (needsImprovement: boolean): readonly AiVisibilityFilter[] =>
    needsImprovement ? ['dateRange', 'engine', 'topic', 'branded'] : ['topic', 'branded']

const RELATIVE_DAY = /^-?\d*[dwmqy](Start|End)?$/i
const ISO_DAY = /^\d{4}-\d{2}-\d{2}/

/** Whether the API can read the value: a date or a relative day, but not hours or "all". */
export const isDateValue = (value: unknown): value is string =>
    typeof value === 'string' && (RELATIVE_DAY.test(value) || ISO_DAY.test(value))

/** Whether a range is longer than the API serves. Only ranges it can measure count: "-120d", or two dates. */
export const isRangeTooLong = (dateFrom: string, dateTo: string | null): boolean => {
    const relativeDays = dateFrom.match(/^-(\d+)d$/)
    if (relativeDays && dateTo === null) {
        return Number(relativeDays[1]) + 1 > MAX_AI_VISIBILITY_RANGE_DAYS
    }
    if (ISO_DAY.test(dateFrom) && (dateTo === null || ISO_DAY.test(dateTo))) {
        const days =
            dayjs(dateTo ?? undefined)
                .startOf('day')
                .diff(dayjs(dateFrom).startOf('day'), 'day') + 1
        return days > MAX_AI_VISIBILITY_RANGE_DAYS
    }
    return false
}

const BRANDED_VALUES = new Set<string>(Object.values(BrandedSegmentEnumApi))

/** The filters a URL sets. A param that is missing or not valid is left out, so the current value stays. */
export const filtersFromSearchParams = (searchParams: Record<string, unknown>): Partial<AiVisibilityFilters> => {
    const filters: Partial<AiVisibilityFilters> = {}
    if (isDateValue(searchParams.date_from)) {
        filters.dateFrom = searchParams.date_from
        filters.dateTo = isDateValue(searchParams.date_to) ? searchParams.date_to : null
    } else if (/^\d+$/.test(String(searchParams.days ?? ''))) {
        // Links from before the date range carry the window as a number of days.
        filters.dateFrom = `-${searchParams.days}d`
        filters.dateTo = null
    }
    if ('engine' in searchParams) {
        filters.engine = typeof searchParams.engine === 'string' && searchParams.engine ? searchParams.engine : null
    }
    if ('topic' in searchParams) {
        filters.topic =
            searchParams.topic === null || searchParams.topic === undefined ? '' : String(searchParams.topic)
    }
    if (typeof searchParams.branded === 'string' && BRANDED_VALUES.has(searchParams.branded)) {
        filters.branded = searchParams.branded as BrandedSegmentEnumApi
    }
    return filters
}

/** Why the filters cannot take a range, as a message for the person who picked it, or null when they can. */
export const dateRangeProblem = (dateFrom: string, dateTo: string | null): string | null => {
    if (!isDateValue(dateFrom) || (dateTo !== null && !isDateValue(dateTo))) {
        return 'AI visibility counts whole days. Pick a range in days, weeks or months.'
    }
    if (isRangeTooLong(dateFrom, dateTo)) {
        return `Pick a date range of ${MAX_AI_VISIBILITY_RANGE_DAYS} days or less.`
    }
    return null
}

/** The search params for the filters. Defaults are left out to keep links short, except the branded segment,
 * which persists per browser, so a link always carries it. */
export const filtersToSearchParams = (filters: AiVisibilityFilters): Record<string, string | number> => ({
    ...(filters.dateFrom !== DEFAULT_AI_VISIBILITY_DATE_FROM || filters.dateTo !== null
        ? { date_from: filters.dateFrom }
        : {}),
    ...(filters.dateTo !== null ? { date_to: filters.dateTo } : {}),
    ...(filters.engine !== null ? { engine: filters.engine } : {}),
    ...(filters.topic !== null ? { topic: filters.topic } : {}),
    branded: filters.branded,
})

/** `searchParams` with the AI visibility params replaced by the filters' own. */
export const withFilterSearchParams = (
    searchParams: Record<string, unknown>,
    filters: AiVisibilityFilters
): Record<string, unknown> => {
    const others = Object.fromEntries(
        Object.entries(searchParams).filter(([key]) => !(AI_VISIBILITY_URL_PARAMS as readonly string[]).includes(key))
    )
    return { ...others, ...filtersToSearchParams(filters) }
}

/** The API query params for the filters. A null engine or topic is left out, so the API counts every one. */
export const filtersToQueryParams = ({
    dateFrom,
    dateTo,
    engine,
    topic,
    branded,
}: AiVisibilityFilters): {
    date_from: string
    date_to?: string
    branded: BrandedSegmentEnumApi
    engine?: string
    topic?: string
} => ({
    date_from: dateFrom,
    ...(dateTo !== null ? { date_to: dateTo } : {}),
    branded,
    ...(engine !== null ? { engine } : {}),
    ...(topic !== null ? { topic } : {}),
})

export const topicLabel = (topic: string): string => topic || 'No topic'
