import { AI_VISIBILITY_URL_PARAMS } from 'scenes/web-analytics/common'

import { BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

export type AiVisibilityFilterTab = 'overview' | 'rankings' | 'prompts' | 'keywords'

export type AiVisibilityFilter = 'dateRange' | 'engine' | 'topic' | 'branded'

export const AI_VISIBILITY_DAYS_OPTIONS = [7, 14, 30, 90] as const
export type AiVisibilityDays = (typeof AI_VISIBILITY_DAYS_OPTIONS)[number]
export const DEFAULT_AI_VISIBILITY_DAYS: AiVisibilityDays = 30

export interface AiVisibilityFilters {
    days: AiVisibilityDays
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

export const daysToDateFrom = (days: AiVisibilityDays): string => `-${days}d`

/** The preset a DateFilter value stands for, or null when it is not one of the presets. */
export const dateFromToDays = (dateFrom: string | null | undefined): AiVisibilityDays | null => {
    const match = dateFrom?.match(/^-(\d+)d$/)
    return match ? toDays(match[1]) : null
}

const toDays = (value: unknown): AiVisibilityDays | null => {
    const days = Number(value)
    return (AI_VISIBILITY_DAYS_OPTIONS as readonly number[]).includes(days) ? (days as AiVisibilityDays) : null
}

const BRANDED_VALUES = new Set<string>(Object.values(BrandedSegmentEnumApi))

/** The filters a URL sets. A param that is missing or not valid is left out, so the current value stays. */
export const filtersFromSearchParams = (searchParams: Record<string, unknown>): Partial<AiVisibilityFilters> => {
    const filters: Partial<AiVisibilityFilters> = {}
    const days = toDays(searchParams.days)
    if (days !== null) {
        filters.days = days
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

/** The search params for the filters. Defaults are left out to keep links short, except the branded segment,
 * which persists per browser, so a link always carries it. */
export const filtersToSearchParams = (filters: AiVisibilityFilters): Record<string, string | number> => ({
    ...(filters.days !== DEFAULT_AI_VISIBILITY_DAYS ? { days: filters.days } : {}),
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
    days,
    engine,
    topic,
    branded,
}: AiVisibilityFilters): { days: number; branded: BrandedSegmentEnumApi; engine?: string; topic?: string } => ({
    days,
    branded,
    ...(engine !== null ? { engine } : {}),
    ...(topic !== null ? { topic } : {}),
})

export const topicLabel = (topic: string): string => topic || 'No topic'
