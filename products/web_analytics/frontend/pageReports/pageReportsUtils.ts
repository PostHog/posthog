import { combineUrl } from 'kea-router'

import { applyPathCleaning } from 'lib/components/PathCleanFilters/pathCleaningUtils'
import { urls } from 'scenes/urls'
import { parseWebAnalyticsURL, WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import type { DateFilterState } from 'scenes/web-analytics/webAnalyticsLogic'

import {
    CompareFilter,
    NodeKind,
    WebAnalyticsConversionGoal,
    WebAnalyticsPropertyFilters,
    WebPageDirectoryMetric,
    WebPageDirectoryQuery,
    WebPageDirectoryValue,
} from '~/queries/schema/schema-general'
import { PathCleaningFilter } from '~/types'

import { changeVsPrevious } from 'products/web_analytics/frontend/searchAndAi/searchAndAiQueries'

export interface PageDirectoryFilters {
    dateFilter: DateFilterState
    compareFilter: CompareFilter
    conversionGoal: WebAnalyticsConversionGoal | null
    filterTestAccounts: boolean
    isPathCleaningEnabled: boolean
    webAnalyticsFilters: WebAnalyticsPropertyFilters
}

export const buildPageDirectoryBaseQuery = ({
    dateFilter,
    compareFilter,
    conversionGoal,
    filterTestAccounts,
    isPathCleaningEnabled,
    webAnalyticsFilters,
}: PageDirectoryFilters): WebPageDirectoryQuery => ({
    kind: NodeKind.WebPageDirectoryQuery,
    dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
    interval: dateFilter.interval,
    compareFilter,
    conversionGoal,
    filterTestAccounts,
    doPathCleaning: isPathCleaningEnabled,
    properties: webAnalyticsFilters,
    excludeStaticAssets: true,
    tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
})

export const SITE_SUMMARY_METRICS: WebPageDirectoryMetric[] = [
    WebPageDirectoryMetric.Visitors,
    WebPageDirectoryMetric.GoogleSearch,
    WebPageDirectoryMetric.AiReferrals,
    WebPageDirectoryMetric.AiCrawls,
]

export const buildSiteTotalsQuery = (baseQuery: WebPageDirectoryQuery): WebPageDirectoryQuery => ({
    ...baseQuery,
    conversionGoal: null,
    pageKeys: [],
    metrics: SITE_SUMMARY_METRICS,
    includeSiteTotals: true,
})

export const valueChange = (value: WebPageDirectoryValue | null | undefined): number | null =>
    value?.previous != null ? changeVsPrevious(value.current, value.previous) : null

export const pageReportUrlForPage = (page: string): string =>
    page.startsWith('/') || /^[a-z]+:\/\//i.test(page) ? page : `https://${page}`

export const pageUrlForHost = (page: string, host: string | null): string => {
    const url = pageReportUrlForPage(page)
    if (!host) {
        return url
    }
    return url.startsWith('/') ? `https://${host}${url}` : url.replace(/^([a-z]+:\/\/)[^/?#]*/i, `$1${host}`)
}

export const pageReportPath = (page: string, searchParams: Record<string, any> = {}): string =>
    combineUrl(urls.webAnalyticsPageReports(), { ...searchParams, pageURL: pageReportUrlForPage(page) }).url

export const looksLikePageUrl = (search: string): boolean => {
    const trimmed = search.trim()
    if (!trimmed || /\s/.test(trimmed)) {
        return false
    }
    return /^https?:\/\//i.test(trimmed) || /^[a-z0-9-]+(\.[a-z0-9-]+)+\/.*/i.test(trimmed)
}

export const pageKeyForUrl = (
    url: string,
    isPathCleaningEnabled: boolean,
    pathCleaningFilters: PathCleaningFilter[],
    selectedHost: string | null
): string => {
    const cleanPath = (pathname: string): string =>
        isPathCleaningEnabled ? applyPathCleaning(pathname, pathCleaningFilters) : pathname
    if (url.startsWith('/')) {
        return `${selectedHost ?? ''}${cleanPath(url.split(/[?#]/)[0])}`
    }
    const parsed = parseWebAnalyticsURL(pageReportUrlForPage(url))
    if (!parsed.isValid || !parsed.pathname) {
        return url
    }
    return `${selectedHost ?? parsed.host ?? ''}${cleanPath(parsed.pathname.replace(/%3C([^/%]*)%3E/gi, '<$1>'))}`
}

export const splitPageKey = (page: string): { host: string | null; path: string } => {
    const slash = page.indexOf('/')
    if (slash <= 0) {
        return { host: null, path: page || '/' }
    }
    return { host: page.slice(0, slash), path: page.slice(slash) }
}
