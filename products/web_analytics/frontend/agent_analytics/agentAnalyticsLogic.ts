import type { BreakPointFunction } from 'kea'
import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import type { PaginationManual } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import type { DateFilterState } from 'scenes/web-analytics/webAnalyticsLogic'

import { performQuery } from '~/queries/query'
import {
    CompareFilter,
    NodeKind,
    WebAgentContentGrouping,
    WebAgentAnalyticsQuery,
    WebAgentAnalyticsQueryType,
    WebAnalyticsConversionGoal,
    WebAnalyticsPropertyFilters,
} from '~/queries/schema/schema-general'
import { IntervalType, TeamPublicType, TeamType } from '~/types'

import * as webAnalyticsApi from 'products/web_analytics/frontend/generated/api'

export type AgentScope = 'live' | 'all'
export type AgentView = 'overview' | 'journeys' | 'issues' | 'readiness'
export type AgentIssueType = 'content_gap' | 'waste' | 'malformed'
export type JourneyTransition = 'start' | 'confirmed' | 'sequential' | 'parallel'

export interface OverviewStats {
    activeClients: number
    activeClientsPrev: number
    agentFamilies: number
    serverRequests: number
    serverRequestsPrev: number
    clientNavigations: number
    clientNavigationsPrev: number
    statusObserved: number
    clientErrors: number
    clientErrorsPrev: number
    wasted: number
    wastedPrev: number
    wastePages: number
    convertedClients: number
    convertedClientsPrev: number
    malformed: number
    malformedPrev: number
    llmsTxtFetches: number
    excludedRequests: number
}

export interface AgentIssue {
    key: string
    type: AgentIssueType
    title: string
    subtitle: string
    demand: number
    demandPrev: number
    changePct: number | null
    topAgent: string | null
    firstSeen: string | null
    lastSeen: string | null
    recommendedFix: string[]
}

export interface PageRead {
    page: string
    fetches: number
    mdFetches: number
    htmlFetches: number
    pairedClients: number
}

export interface NextHop {
    path: string
    requests: number
    notFound: number
}

export interface DemandRow {
    page: string
    host: string
    path: string
    demand: number
}

export interface IssueVariant {
    variant: string
    demand: number
    topAgent: string | null
    firstSeen: string | null
}

export interface RequestAnatomyRow {
    agent: string
    requests: number
    requestedMarkdown: number
    retryPairs: number
    errors: number
}

export interface JourneySummary {
    totalJourneys: number
    medianPages: number
    medianRequests: number
    medianDurationSeconds: number
    journeysWithErrors: number
}

export interface JourneyRow {
    journeyKey: string
    started: string | null
    agent: string
    host: string
    pages: number
    requests: number
    durationSeconds: number
    errors: number
}

export interface JourneyStep {
    timestamp: string | null
    path: string
    status: number
    format: string
    referrer: string
    transition: JourneyTransition
}

export interface LlmsTxtSourceForm {
    url: string
}

export interface LlmsTxtLink {
    host: string | null
    path: string
}

export interface DemandCoverage {
    listedPages: number
    missingPages: number
    totalDemand: number
    listedDemand: number
    observedHosts: string[]
    hasMatchingHost: boolean
}

const EMPTY_OVERVIEW: OverviewStats = {
    activeClients: 0,
    activeClientsPrev: 0,
    agentFamilies: 0,
    serverRequests: 0,
    serverRequestsPrev: 0,
    clientNavigations: 0,
    clientNavigationsPrev: 0,
    statusObserved: 0,
    clientErrors: 0,
    clientErrorsPrev: 0,
    wasted: 0,
    wastedPrev: 0,
    wastePages: 0,
    convertedClients: 0,
    convertedClientsPrev: 0,
    malformed: 0,
    malformedPrev: 0,
    llmsTxtFetches: 0,
    excludedRequests: 0,
}

export const EMPTY_JOURNEY_SUMMARY: JourneySummary = {
    totalJourneys: 0,
    medianPages: 0,
    medianRequests: 0,
    medianDurationSeconds: 0,
    journeysWithErrors: 0,
}

const validateLlmsTxtSource = ({ url }: LlmsTxtSourceForm): { url: string | undefined } => {
    if (!url.trim()) {
        return { url: 'Enter the URL of your llms.txt file' }
    }
    try {
        const parsedUrl = new URL(url)
        if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
            return { url: 'Enter an HTTP or HTTPS URL' }
        }
    } catch {
        return { url: 'Enter a valid URL' }
    }
    return { url: undefined }
}

const llmsTxtFetchErrorMessage = (error: unknown): string => {
    const apiError = error as {
        data?: { url?: string[]; detail?: string }
        detail?: string
        message?: string
    }
    return (
        apiError.data?.url?.[0] ??
        apiError.data?.detail ??
        apiError.detail ??
        apiError.message ??
        'Could not load llms.txt. Check the URL and try again.'
    )
}

const queryErrorMessage = (error: unknown): string => {
    const apiError = error as { detail?: string; message?: string }
    return apiError?.detail ?? apiError?.message ?? 'Could not load this query.'
}

const errorForQuery =
    (queryType: WebAgentAnalyticsQueryType) =>
    (state: string | null, payload: { queryType: WebAgentAnalyticsQueryType; error: string | null }): string | null =>
        payload.queryType === queryType ? payload.error : state

const num = (value: unknown): number => Number(value ?? 0)

const str = (value: unknown): string => (value == null ? '' : String(value))

const columnIndex = (columns: string[] | undefined, name: string): number => (columns ?? []).indexOf(name)

export const parseOverviewRow = (columns: string[] | undefined, results: unknown[][] | undefined): OverviewStats => {
    const row = (results ?? [])[0]
    if (!Array.isArray(row)) {
        return EMPTY_OVERVIEW
    }
    const get = (name: string): number => {
        const idx = columnIndex(columns, name)
        return idx >= 0 ? num(row[idx]) : 0
    }
    return {
        activeClients: get('active_clients'),
        activeClientsPrev: get('active_clients_prev'),
        agentFamilies: get('agent_families'),
        serverRequests: get('server_requests'),
        serverRequestsPrev: get('server_requests_prev'),
        clientNavigations: get('client_navigations'),
        clientNavigationsPrev: get('client_navigations_prev'),
        statusObserved: get('status_observed'),
        clientErrors: get('client_errors'),
        clientErrorsPrev: get('client_errors_prev'),
        wasted: get('wasted'),
        wastedPrev: get('wasted_prev'),
        wastePages: get('waste_pages'),
        convertedClients: get('converted_agents'),
        convertedClientsPrev: get('converted_agents_prev'),
        malformed: get('malformed'),
        malformedPrev: get('malformed_prev'),
        llmsTxtFetches: get('llms_txt_fetches'),
        excludedRequests: get('excluded_requests'),
    }
}

export const changePct = (current: number, previous: number | null): number | null => {
    if (previous === null || previous <= 0) {
        return null
    }
    return Math.round(((current - previous) / previous) * 100)
}

const contentGapFix = (path: string): string[] => [
    path
        ? `Publish a page at ${path}, or redirect it if the content moved`
        : 'Publish the requested page, or redirect it if the content moved',
    'Redirect the other requested URLs listed below to that page',
    'List the page in llms.txt and link its markdown version',
]

const WASTE_FIX = ['List markdown versions in llms.txt', 'Advertise markdown versions with an HTTP Link header']

const MALFORMED_FIX = [
    'Check whether your own pages link to unfilled URL templates',
    'Redirect the malformed paths to the closest valid page',
]

export const parseIssuesResponse = (columns: string[] | undefined, results: unknown[][] | undefined): AgentIssue[] => {
    const keyIdx = columnIndex(columns, 'intent_key')
    const pathIdx = columnIndex(columns, 'intent_path')
    const demandIdx = columnIndex(columns, 'demand')
    const demandPrevIdx = columnIndex(columns, 'demand_prev')
    const variantsIdx = columnIndex(columns, 'variants')
    const agentIdx = columnIndex(columns, 'top_agent')
    const firstSeenIdx = columnIndex(columns, 'first_seen')
    const lastSeenIdx = columnIndex(columns, 'last_seen')

    return (results ?? [])
        .filter(Array.isArray)
        .map((row): AgentIssue | null => {
            const key = str(row[keyIdx])
            if (!key) {
                return null
            }
            const intentPath = str(row[pathIdx])
            const demand = num(row[demandIdx])
            const demandPrev = num(row[demandPrevIdx])
            const variants = num(row[variantsIdx])
            return {
                key,
                type: 'content_gap',
                title: `Agents requested ${intentPath || '(unknown page)'}`,
                subtitle: `${variants} requested URL ${variants === 1 ? 'variant' : 'variants'}`,
                demand,
                demandPrev,
                changePct: changePct(demand, demandPrev),
                topAgent: str(row[agentIdx]) || null,
                firstSeen: str(row[firstSeenIdx]) || null,
                lastSeen: str(row[lastSeenIdx]) || null,
                recommendedFix: contentGapFix(intentPath),
            }
        })
        .filter((issue): issue is AgentIssue => issue !== null)
}

export const synthesizeAuxIssues = (overview: OverviewStats): AgentIssue[] => {
    const issues: AgentIssue[] = []
    if (overview.wasted > 0) {
        issues.push({
            key: 'waste:md-twins',
            type: 'waste',
            title: 'Agents fetch both HTML and markdown versions',
            subtitle: `${overview.wastePages} ${overview.wastePages === 1 ? 'page' : 'pages'} affected`,
            demand: overview.wasted,
            demandPrev: overview.wastedPrev,
            changePct: changePct(overview.wasted, overview.wastedPrev),
            topAgent: null,
            firstSeen: null,
            lastSeen: null,
            recommendedFix: WASTE_FIX,
        })
    }
    if (overview.malformed > 0) {
        issues.push({
            key: 'malformed:null-urls',
            type: 'malformed',
            title: 'Agents request malformed /null URLs',
            subtitle: 'The requested path contains an unfilled URL template value',
            demand: overview.malformed,
            demandPrev: overview.malformedPrev,
            changePct: changePct(overview.malformed, overview.malformedPrev),
            topAgent: null,
            firstSeen: null,
            lastSeen: null,
            recommendedFix: MALFORMED_FIX,
        })
    }
    return issues
}

export const parseWhatAgentsRead = (columns: string[] | undefined, results: unknown[][] | undefined): PageRead[] => {
    const pageIdx = columnIndex(columns, 'page')
    const fetchesIdx = columnIndex(columns, 'fetches')
    const mdIdx = columnIndex(columns, 'md_fetches')
    const htmlIdx = columnIndex(columns, 'html_fetches')
    const pairedClientsIdx = columnIndex(columns, 'paired_clients')
    return (results ?? []).filter(Array.isArray).map((row) => ({
        page: str(row[pageIdx]),
        fetches: num(row[fetchesIdx]),
        mdFetches: num(row[mdIdx]),
        htmlFetches: num(row[htmlIdx]),
        pairedClients: num(row[pairedClientsIdx]),
    }))
}

export const parseNextHops = (columns: string[] | undefined, results: unknown[][] | undefined): NextHop[] => {
    const pathIdx = columnIndex(columns, 'next_path')
    const requestsIdx = columnIndex(columns, 'requests')
    const notFoundIdx = columnIndex(columns, 'not_found')
    return (results ?? []).filter(Array.isArray).map((row) => ({
        path: str(row[pathIdx]),
        requests: num(row[requestsIdx]),
        notFound: num(row[notFoundIdx]),
    }))
}

export const parseDemandRows = (columns: string[] | undefined, results: unknown[][] | undefined): DemandRow[] => {
    const pageIdx = columnIndex(columns, 'page')
    const hostIdx = columnIndex(columns, 'host')
    const pathIdx = columnIndex(columns, 'path')
    const demandIdx = columnIndex(columns, 'demand')
    return (results ?? []).filter(Array.isArray).map((row) => ({
        page: str(row[pageIdx]),
        host: str(row[hostIdx]),
        path: str(row[pathIdx]),
        demand: num(row[demandIdx]),
    }))
}

export const parseVariants = (columns: string[] | undefined, results: unknown[][] | undefined): IssueVariant[] => {
    const variantIdx = columnIndex(columns, 'variant')
    const demandIdx = columnIndex(columns, 'demand')
    const agentIdx = columnIndex(columns, 'top_agent')
    const firstSeenIdx = columnIndex(columns, 'first_seen')
    return (results ?? []).filter(Array.isArray).map((row) => ({
        variant: str(row[variantIdx]),
        demand: num(row[demandIdx]),
        topAgent: str(row[agentIdx]) || null,
        firstSeen: str(row[firstSeenIdx]) || null,
    }))
}

export const parseRequestAnatomy = (
    columns: string[] | undefined,
    results: unknown[][] | undefined
): RequestAnatomyRow[] => {
    const agentIdx = columnIndex(columns, 'agent')
    const requestsIdx = columnIndex(columns, 'requests')
    const requestedMdIdx = columnIndex(columns, 'requested_markdown')
    const retryIdx = columnIndex(columns, 'retry_pairs')
    const errorsIdx = columnIndex(columns, 'errors')
    return (results ?? []).filter(Array.isArray).map((row) => ({
        agent: str(row[agentIdx]) || 'Unclassified agent',
        requests: num(row[requestsIdx]),
        requestedMarkdown: num(row[requestedMdIdx]),
        retryPairs: num(row[retryIdx]),
        errors: num(row[errorsIdx]),
    }))
}

export const parseJourneySummary = (
    columns: string[] | undefined,
    results: unknown[][] | undefined
): JourneySummary => {
    const row = (results ?? [])[0]
    if (!Array.isArray(row)) {
        return EMPTY_JOURNEY_SUMMARY
    }
    const get = (name: string): number => {
        const idx = columnIndex(columns, name)
        return idx >= 0 ? num(row[idx]) : 0
    }
    return {
        totalJourneys: get('total_journeys'),
        medianPages: get('median_pages'),
        medianRequests: get('median_requests'),
        medianDurationSeconds: get('median_duration_seconds'),
        journeysWithErrors: get('journeys_with_errors'),
    }
}

export const parseJourneys = (columns: string[] | undefined, results: unknown[][] | undefined): JourneyRow[] => {
    const keyIdx = columnIndex(columns, 'journey_key')
    const startedIdx = columnIndex(columns, 'started')
    const agentIdx = columnIndex(columns, 'agent')
    const hostIdx = columnIndex(columns, 'host')
    const pagesIdx = columnIndex(columns, 'pages')
    const requestsIdx = columnIndex(columns, 'requests')
    const durationIdx = columnIndex(columns, 'duration_seconds')
    const errorsIdx = columnIndex(columns, 'errors')
    return (results ?? [])
        .filter(Array.isArray)
        .map((row): JourneyRow | null => {
            const journeyKey = str(row[keyIdx])
            if (!journeyKey) {
                return null
            }
            return {
                journeyKey,
                started: str(row[startedIdx]) || null,
                agent: str(row[agentIdx]) || 'Unclassified agent',
                host: str(row[hostIdx]),
                pages: num(row[pagesIdx]),
                requests: num(row[requestsIdx]),
                durationSeconds: num(row[durationIdx]),
                errors: num(row[errorsIdx]),
            }
        })
        .filter((journey): journey is JourneyRow => journey !== null)
}

const JOURNEY_TRANSITIONS: JourneyTransition[] = ['start', 'confirmed', 'sequential', 'parallel']

export const parseJourneyDetail = (columns: string[] | undefined, results: unknown[][] | undefined): JourneyStep[] => {
    const timestampIdx = columnIndex(columns, 'timestamp')
    const pathIdx = columnIndex(columns, 'path')
    const statusIdx = columnIndex(columns, 'status')
    const formatIdx = columnIndex(columns, 'format')
    const referrerIdx = columnIndex(columns, 'referrer')
    const transitionIdx = columnIndex(columns, 'transition')
    return (results ?? []).filter(Array.isArray).map((row) => {
        const transition = str(row[transitionIdx])
        return {
            timestamp: str(row[timestampIdx]) || null,
            path: str(row[pathIdx]),
            status: num(row[statusIdx]),
            format: str(row[formatIdx]),
            referrer: str(row[referrerIdx]),
            transition: (JOURNEY_TRANSITIONS.includes(transition as JourneyTransition)
                ? transition
                : 'sequential') as JourneyTransition,
        }
    })
}

const llmsTxtContentPath = (path: string): string => (path.endsWith('.md') ? path.slice(0, -3) || '/' : path)

export const llmsTxtLinkKey = (host: string | null, path: string): string =>
    `${host?.toLowerCase() ?? '*'}\n${llmsTxtContentPath(path)}`

export const parseLlmsTxtLinks = (input: string, baseUrl: string | null): Map<string, LlmsTxtLink> => {
    const links = new Map<string, LlmsTxtLink>()
    for (const rawLine of input.split('\n')) {
        const candidates = new Set<string>()
        for (const match of rawLine.matchAll(/\]\(\s*<?([^\s)>]+)>?(?:\s+['"][^'"]*['"])?\s*\)/g)) {
            candidates.add(match[1])
        }
        for (const match of rawLine.match(/https?:\/\/[^\s)<]+|\/[^\s)<]+/g) ?? []) {
            candidates.add(match)
        }
        for (const candidate of candidates) {
            try {
                if (candidate.startsWith('/') && !baseUrl) {
                    const link = { host: null, path: candidate }
                    links.set(llmsTxtLinkKey(link.host, link.path), link)
                    continue
                }
                const parsedUrl = baseUrl ? new URL(candidate, baseUrl) : new URL(candidate)
                if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
                    continue
                }
                const link = { host: parsedUrl.host.toLowerCase(), path: parsedUrl.pathname || '/' }
                links.set(llmsTxtLinkKey(link.host, link.path), link)
            } catch {
                continue
            }
        }
    }
    return links
}

export const isDemandCovered = (row: DemandRow, links: Map<string, LlmsTxtLink>): boolean =>
    links.has(llmsTxtLinkKey(row.host, row.path)) || links.has(llmsTxtLinkKey(null, row.path))

export const summarizeDemandCoverage = (
    demandRows: DemandRow[],
    llmsTxtLinks: Map<string, LlmsTxtLink>
): DemandCoverage => {
    let listedPages = 0
    let totalDemand = 0
    let listedDemand = 0
    const observedHosts = new Set<string>()
    const listedHosts = new Set<string>()
    let hasWildcardLinks = false

    for (const link of llmsTxtLinks.values()) {
        if (link.host) {
            listedHosts.add(link.host.toLowerCase())
        } else {
            hasWildcardLinks = true
        }
    }
    for (const row of demandRows) {
        const host = row.host.toLowerCase()
        if (host) {
            observedHosts.add(host)
        }
        totalDemand += row.demand
        if (isDemandCovered(row, llmsTxtLinks)) {
            listedPages += 1
            listedDemand += row.demand
        }
    }

    const sortedObservedHosts = [...observedHosts].sort()
    return {
        listedPages,
        missingPages: demandRows.length - listedPages,
        totalDemand,
        listedDemand,
        observedHosts: sortedObservedHosts,
        hasMatchingHost: hasWildcardLinks || sortedObservedHosts.some((host) => listedHosts.has(host)),
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface agentAnalyticsLogicValues {
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    compareFilter: CompareFilter // webAnalyticsLogic
    conversionGoal: WebAnalyticsConversionGoal | null // webAnalyticsLogic
    dateFilter: DateFilterState // webAnalyticsLogic
    filterTestAccounts: boolean // webAnalyticsLogic
    webAnalyticsFilters: WebAnalyticsPropertyFilters // webAnalyticsLogic
    anyLoading: boolean
    contentGapIssues: AgentIssue[]
    contentGapIssuesError: string | null
    contentGapIssuesLoading: boolean
    demandCoverage: DemandCoverage
    demandRows: DemandRow[]
    demandRowsError: string | null
    demandRowsLoading: boolean
    includeCrawlers: boolean
    isLlmsTxtSourceSubmitting: boolean
    isLlmsTxtSourceValid: boolean
    issues: AgentIssue[]
    issuesPage: number
    journeyDetail: JourneyStep[]
    journeyDetailError: string | null
    journeyDetailLoading: boolean
    journeySummary: JourneySummary | null
    journeySummaryError: string | null
    journeySummaryLoading: boolean
    journeys: JourneyRow[]
    journeysError: string | null
    journeysLoading: boolean
    llmsTxtFetchError: string | null
    llmsTxtInput: string
    llmsTxtLinks: Map<string, LlmsTxtLink>
    llmsTxtLoadedUrl: string | null
    llmsTxtSource: LlmsTxtSourceForm
    llmsTxtSourceAllErrors: Record<string, any>
    llmsTxtSourceChanged: boolean
    llmsTxtSourceErrors: DeepPartialMap<LlmsTxtSourceForm, ValidationErrorType>
    llmsTxtSourceHasErrors: boolean
    llmsTxtSourceManualErrors: Record<string, any>
    llmsTxtSourceTouched: boolean
    llmsTxtSourceTouches: Record<string, boolean>
    llmsTxtSourceValidationErrors: DeepPartialMap<LlmsTxtSourceForm, ValidationErrorType>
    nextHops: NextHop[]
    nextHopsError: string | null
    nextHopsLoading: boolean
    overview: OverviewStats | null
    overviewError: string | null
    overviewLoading: boolean
    requestAnatomy: RequestAnatomyRow[]
    requestAnatomyError: string | null
    requestAnatomyLoading: boolean
    resultHasMore: Partial<Record<WebAgentAnalyticsQueryType, boolean>>
    resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>
    resultPaginations: Partial<Record<WebAgentAnalyticsQueryType, PaginationManual>>
    scope: AgentScope
    selectedIssue: AgentIssue | null
    selectedIssueKey: string | null
    selectedJourney: JourneyRow | null
    selectedJourneyKey: string | null
    showLlmsTxtSourceErrors: boolean
    topIssues: AgentIssue[]
    variants: IssueVariant[]
    variantsError: string | null
    variantsLoading: boolean
    view: AgentView
    whatAgentsRead: PageRead[]
    whatAgentsReadError: string | null
    whatAgentsReadLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface agentAnalyticsLogicActions {
    setWebAnalyticsCompareFilter: (compareFilter: CompareFilter) => {
        compareFilter: CompareFilter
    } // webAnalyticsLogic
    setWebAnalyticsConversionGoal: (conversionGoal: WebAnalyticsConversionGoal | null) => {
        conversionGoal: WebAnalyticsConversionGoal | null
    } // webAnalyticsLogic
    setWebAnalyticsCountryFilter: (countryCode: string | null) => {
        countryCode: string | null
    } // webAnalyticsLogic
    setWebAnalyticsDateInterval: (interval: IntervalType) => {
        interval: IntervalType
    } // webAnalyticsLogic
    setWebAnalyticsDates: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    } // webAnalyticsLogic
    setWebAnalyticsDatesAndInterval: (
        dateFrom: string | null,
        dateTo: string | null,
        interval: IntervalType
    ) => {
        dateFrom: string | null
        dateTo: string | null
        interval: IntervalType
    } // webAnalyticsLogic
    setWebAnalyticsDeviceTypeFilter: (deviceType: null | import('scenes/web-analytics/common').DeviceType) => {
        deviceType: null | import('scenes/web-analytics/common').DeviceType
    } // webAnalyticsLogic
    setWebAnalyticsDomainFilter: (domain: string | null) => {
        domain: string | null
    } // webAnalyticsLogic
    setWebAnalyticsFilterTestAccounts: (shouldFilterTestAccounts: boolean) => {
        shouldFilterTestAccounts: boolean
    } // webAnalyticsLogic
    setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
        webAnalyticsFilters: WebAnalyticsPropertyFilters
    } // webAnalyticsLogic
    setWebAnalyticsReferrerFilter: (referrer: string | null) => {
        referrer: string | null
    } // webAnalyticsLogic
    loadDemandRows: () => {
        value: true
    }
    loadDemandRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDemandRowsSuccess: (
        demandRows: DemandRow[],
        payload?: {
            value: true
        }
    ) => {
        demandRows: DemandRow[]
        payload?: {
            value: true
        }
    }
    loadIssues: () => {
        value: true
    }
    loadIssuesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadIssuesSuccess: (
        contentGapIssues: AgentIssue[],
        payload?: {
            value: true
        }
    ) => {
        contentGapIssues: AgentIssue[]
        payload?: {
            value: true
        }
    }
    loadJourneyDetail: () => {
        value: true
    }
    loadJourneyDetailFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadJourneyDetailSuccess: (
        journeyDetail: JourneyStep[],
        payload?: {
            value: true
        }
    ) => {
        journeyDetail: JourneyStep[]
        payload?: {
            value: true
        }
    }
    loadJourneySummary: () => {
        value: true
    }
    loadJourneySummaryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadJourneySummarySuccess: (
        journeySummary: JourneySummary,
        payload?: {
            value: true
        }
    ) => {
        journeySummary: JourneySummary
        payload?: {
            value: true
        }
    }
    loadJourneys: () => {
        value: true
    }
    loadJourneysFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadJourneysSuccess: (
        journeys: JourneyRow[],
        payload?: {
            value: true
        }
    ) => {
        journeys: JourneyRow[]
        payload?: {
            value: true
        }
    }
    loadNextHops: () => {
        value: true
    }
    loadNextHopsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadNextHopsSuccess: (
        nextHops: NextHop[],
        payload?: {
            value: true
        }
    ) => {
        nextHops: NextHop[]
        payload?: {
            value: true
        }
    }
    loadOverview: () => {
        value: true
    }
    loadOverviewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOverviewSuccess: (
        overview: OverviewStats,
        payload?: {
            value: true
        }
    ) => {
        overview: OverviewStats
        payload?: {
            value: true
        }
    }
    loadRequestAnatomy: () => {
        value: true
    }
    loadRequestAnatomyFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRequestAnatomySuccess: (
        requestAnatomy: RequestAnatomyRow[],
        payload?: {
            value: true
        }
    ) => {
        requestAnatomy: RequestAnatomyRow[]
        payload?: {
            value: true
        }
    }
    loadVariants: () => {
        value: true
    }
    loadVariantsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadVariantsSuccess: (
        variants: IssueVariant[],
        payload?: {
            value: true
        }
    ) => {
        variants: IssueVariant[]
        payload?: {
            value: true
        }
    }
    loadWhatAgentsRead: () => {
        value: true
    }
    loadWhatAgentsReadFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadWhatAgentsReadSuccess: (
        whatAgentsRead: PageRead[],
        payload?: {
            value: true
        }
    ) => {
        whatAgentsRead: PageRead[]
        payload?: {
            value: true
        }
    }
    refresh: () => {
        value: true
    }
    resetLlmsTxtSource: (values?: LlmsTxtSourceForm) => {
        values?: LlmsTxtSourceForm
    }
    setLlmsTxtFromUrl: (
        content: string,
        url: string
    ) => {
        content: string
        url: string
    }
    setLlmsTxtSourceManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setLlmsTxtSourceValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setLlmsTxtSourceValues: (values: DeepPartial<LlmsTxtSourceForm>) => {
        values: DeepPartial<LlmsTxtSourceForm>
    }
    setQueryError: (
        queryType: WebAgentAnalyticsQueryType,
        error: string | null
    ) => {
        error: string | null
        queryType: WebAgentAnalyticsQueryType
    }
    setResultHasMore: (
        queryType: WebAgentAnalyticsQueryType,
        hasMore: boolean
    ) => {
        hasMore: boolean
        queryType: WebAgentAnalyticsQueryType
    }
    setResultPage: (
        queryType: WebAgentAnalyticsQueryType,
        page: number
    ) => {
        page: number
        queryType: WebAgentAnalyticsQueryType
    }
    setScope: (scope: AgentScope) => {
        scope: AgentScope
    }
    setSelectedIssueKey: (key: string | null) => {
        key: string | null
    }
    setSelectedJourneyKey: (journeyKey: string | null) => {
        journeyKey: string | null
    }
    setView: (view: AgentView) => {
        view: AgentView
    }
    submitLlmsTxtSource: () => {
        value: boolean
    }
    submitLlmsTxtSourceFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitLlmsTxtSourceRequest: (llmsTxtSource: LlmsTxtSourceForm) => {
        llmsTxtSource: LlmsTxtSourceForm
    }
    submitLlmsTxtSourceSuccess: (llmsTxtSource: LlmsTxtSourceForm) => {
        llmsTxtSource: LlmsTxtSourceForm
    }
    touchLlmsTxtSourceField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface agentAnalyticsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        includeCrawlers: (scope: AgentScope) => boolean
        anyLoading: (
            overviewLoading: boolean,
            contentGapIssuesLoading: boolean,
            whatAgentsReadLoading: boolean,
            nextHopsLoading: boolean,
            demandRowsLoading: boolean,
            variantsLoading: boolean,
            requestAnatomyLoading: boolean,
            journeySummaryLoading: boolean,
            journeysLoading: boolean,
            journeyDetailLoading: boolean
        ) => boolean
        demandCoverage: (demandRows: DemandRow[], llmsTxtLinks: Map<string, LlmsTxtLink>) => DemandCoverage
        issuesPage: (resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>) => number
        issues: (contentGapIssues: AgentIssue[], overview: OverviewStats | null, issuesPage: number) => AgentIssue[]
        topIssues: (issues: AgentIssue[]) => AgentIssue[]
        selectedIssue: (issues: AgentIssue[], selectedIssueKey: string | null) => AgentIssue | null
        selectedJourney: (journeys: JourneyRow[], selectedJourneyKey: string | null) => JourneyRow | null
        resultPaginations: (
            resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>,
            resultHasMore: Partial<Record<WebAgentAnalyticsQueryType, boolean>>
        ) => Partial<Record<WebAgentAnalyticsQueryType, PaginationManual>>
        llmsTxtLinks: (llmsTxtInput: string, llmsTxtLoadedUrl: string | null) => Map<string, LlmsTxtLink>
    }
}

export type agentAnalyticsLogicType = MakeLogicType<
    agentAnalyticsLogicValues,
    agentAnalyticsLogicActions,
    Record<string, any>,
    agentAnalyticsLogicMeta
>

const OVERVIEW_ISSUE_COUNT = 4
const WHAT_AGENTS_READ_LIMIT = 5
const RESULT_PAGE_SIZE = 25
const FIRST_PAGE_ISSUE_RESULT_LIMIT = RESULT_PAGE_SIZE - 2
const JOURNEY_DETAIL_LIMIT = 50

const PAGINATED_QUERY_TYPES: readonly WebAgentAnalyticsQueryType[] = [
    WebAgentAnalyticsQueryType.Issues,
    WebAgentAnalyticsQueryType.Transitions,
    WebAgentAnalyticsQueryType.Demand,
    WebAgentAnalyticsQueryType.IssueVariants,
    WebAgentAnalyticsQueryType.RequestAnatomy,
    WebAgentAnalyticsQueryType.Journeys,
]

interface QueryOptions {
    intentKey?: string
    journeyKey?: string
    limit?: number
    offset?: number
}

const resultPage = (
    resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>,
    queryType: WebAgentAnalyticsQueryType
): number => resultPages[queryType] ?? 1

const paginatedQueryOptions = (
    resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>,
    queryType: WebAgentAnalyticsQueryType
): QueryOptions => {
    const page = resultPage(resultPages, queryType)
    if (queryType === WebAgentAnalyticsQueryType.Issues) {
        return page === 1
            ? { limit: FIRST_PAGE_ISSUE_RESULT_LIMIT, offset: 0 }
            : {
                  limit: RESULT_PAGE_SIZE,
                  offset: FIRST_PAGE_ISSUE_RESULT_LIMIT + (page - 2) * RESULT_PAGE_SIZE,
              }
    }
    return { limit: RESULT_PAGE_SIZE, offset: (page - 1) * RESULT_PAGE_SIZE }
}

export const agentAnalyticsLogic = kea<agentAnalyticsLogicType>([
    path(['products', 'webAnalytics', 'agentAnalyticsLogic']),
    connect(() => ({
        actions: [
            webAnalyticsLogic,
            [
                'setCompareFilter as setWebAnalyticsCompareFilter',
                'setDateInterval as setWebAnalyticsDateInterval',
                'setDates as setWebAnalyticsDates',
                'setDatesAndInterval as setWebAnalyticsDatesAndInterval',
                'setShouldFilterTestAccounts as setWebAnalyticsFilterTestAccounts',
                'setConversionGoal as setWebAnalyticsConversionGoal',
                'setWebAnalyticsFilters',
                'setDomainFilter as setWebAnalyticsDomainFilter',
                'setDeviceTypeFilter as setWebAnalyticsDeviceTypeFilter',
                'setCountryFilter as setWebAnalyticsCountryFilter',
                'setReferrerFilter as setWebAnalyticsReferrerFilter',
            ],
        ],
        values: [
            webAnalyticsLogic,
            [
                'dateFilter',
                'shouldFilterTestAccounts as filterTestAccounts',
                'compareFilter',
                'conversionGoal',
                'webAnalyticsFilters',
            ],
            teamLogic,
            ['currentTeam'],
        ],
    })),
    actions({
        setView: (view: AgentView) => ({ view }),
        setScope: (scope: AgentScope) => ({ scope }),
        setSelectedJourneyKey: (journeyKey: string | null) => ({ journeyKey }),
        setResultHasMore: (queryType: WebAgentAnalyticsQueryType, hasMore: boolean) => ({ queryType, hasMore }),
        setResultPage: (queryType: WebAgentAnalyticsQueryType, page: number) => ({ queryType, page }),
        setQueryError: (queryType: WebAgentAnalyticsQueryType, error: string | null) => ({ queryType, error }),
        setSelectedIssueKey: (key: string | null) => ({ key }),
        setLlmsTxtFromUrl: (content: string, url: string) => ({ content, url }),
        refresh: true,
        loadOverview: true,
        loadIssues: true,
        loadWhatAgentsRead: true,
        loadNextHops: true,
        loadDemandRows: true,
        loadVariants: true,
        loadRequestAnatomy: true,
        loadJourneySummary: true,
        loadJourneys: true,
        loadJourneyDetail: true,
    }),
    forms(({ actions, values }) => ({
        llmsTxtSource: {
            defaults: { url: '' } as LlmsTxtSourceForm,
            errors: validateLlmsTxtSource,
            submit: async ({ url }: LlmsTxtSourceForm) => {
                if (!values.currentTeam) {
                    throw new Error('Select a project before loading llms.txt.')
                }
                const normalizedUrl = url.trim()
                const response = await webAnalyticsApi.webAnalyticsFetchLlmsTxt(String(values.currentTeam.id), {
                    url: normalizedUrl,
                })
                actions.setLlmsTxtFromUrl(response.content, response.url)
            },
        },
    })),
    loaders(({ values, actions, cache }) => {
        const signalFor = (key: string): AbortSignal => {
            const abortController = new AbortController()
            cache.disposables.add(() => () => abortController.abort(), key, { pauseOnPageHidden: false })
            return abortController.signal
        }

        const runQuery = async (
            queryType: WebAgentAnalyticsQueryType,
            breakpoint: BreakPointFunction,
            opts: QueryOptions = {}
        ): Promise<{ columns?: string[]; results?: unknown[][] }> => {
            await breakpoint(300)
            const paginated = PAGINATED_QUERY_TYPES.includes(queryType)
            const { limit, offset, intentKey, journeyKey } = {
                ...(paginated ? paginatedQueryOptions(values.resultPages, queryType) : {}),
                ...opts,
            }
            const node: WebAgentAnalyticsQuery = {
                kind: NodeKind.WebAgentAnalyticsQuery,
                queryType,
                includeCrawlers: values.includeCrawlers,
                contentGrouping: WebAgentContentGrouping.Normalized,
                llmsTxtUrl: values.llmsTxtLoadedUrl ?? undefined,
                limit:
                    limit ??
                    (queryType === WebAgentAnalyticsQueryType.PageRequests ? WHAT_AGENTS_READ_LIMIT : undefined),
                offset,
                intentKey,
                journeyKey,
                dateRange: {
                    date_from: values.dateFilter.dateFrom,
                    date_to: values.dateFilter.dateTo,
                },
                interval: values.dateFilter.interval,
                compareFilter: values.compareFilter,
                conversionGoal: queryType === WebAgentAnalyticsQueryType.Overview ? values.conversionGoal : undefined,
                filterTestAccounts: values.filterTestAccounts,
                properties: values.webAnalyticsFilters,
            }
            let response
            try {
                response = await performQuery(node, { signal: signalFor(queryType) })
            } catch (error) {
                breakpoint()
                actions.setQueryError(queryType, queryErrorMessage(error))
                return {}
            }
            breakpoint()
            if (paginated) {
                actions.setResultHasMore(queryType, response.hasMore ?? false)
            }
            return {
                columns: response.columns as string[] | undefined,
                results: response.results as unknown[][] | undefined,
            }
        }

        return {
            overview: [
                null as OverviewStats | null,
                {
                    loadOverview: async (_, breakpoint: BreakPointFunction) => {
                        const { columns, results } = await runQuery(WebAgentAnalyticsQueryType.Overview, breakpoint)
                        return parseOverviewRow(columns, results)
                    },
                },
            ],
            contentGapIssues: [
                [] as AgentIssue[],
                {
                    loadIssues: async (_, breakpoint: BreakPointFunction) => {
                        const { columns, results } = await runQuery(WebAgentAnalyticsQueryType.Issues, breakpoint)
                        return parseIssuesResponse(columns, results)
                    },
                },
            ],
            whatAgentsRead: [
                [] as PageRead[],
                {
                    loadWhatAgentsRead: async (_, breakpoint: BreakPointFunction) => {
                        const { columns, results } = await runQuery(WebAgentAnalyticsQueryType.PageRequests, breakpoint)
                        return parseWhatAgentsRead(columns, results)
                    },
                },
            ],
            nextHops: [
                [] as NextHop[],
                {
                    loadNextHops: async (_, breakpoint: BreakPointFunction) => {
                        const { columns, results } = await runQuery(WebAgentAnalyticsQueryType.Transitions, breakpoint)
                        return parseNextHops(columns, results)
                    },
                },
            ],
            demandRows: [
                [] as DemandRow[],
                {
                    loadDemandRows: async (_, breakpoint: BreakPointFunction) => {
                        const { columns, results } = await runQuery(WebAgentAnalyticsQueryType.Demand, breakpoint)
                        return parseDemandRows(columns, results)
                    },
                },
            ],
            variants: [
                [] as IssueVariant[],
                {
                    loadVariants: async (_, breakpoint: BreakPointFunction) => {
                        const { selectedIssueKey, selectedIssue } = values
                        if (!selectedIssueKey || selectedIssue?.type !== 'content_gap') {
                            return []
                        }
                        const { columns, results } = await runQuery(
                            WebAgentAnalyticsQueryType.IssueVariants,
                            breakpoint,
                            { intentKey: selectedIssueKey }
                        )
                        return parseVariants(columns, results)
                    },
                },
            ],
            requestAnatomy: [
                [] as RequestAnatomyRow[],
                {
                    loadRequestAnatomy: async (_, breakpoint: BreakPointFunction) => {
                        const { columns, results } = await runQuery(
                            WebAgentAnalyticsQueryType.RequestAnatomy,
                            breakpoint
                        )
                        return parseRequestAnatomy(columns, results)
                    },
                },
            ],
            journeySummary: [
                null as JourneySummary | null,
                {
                    loadJourneySummary: async (_, breakpoint: BreakPointFunction) => {
                        const { columns, results } = await runQuery(
                            WebAgentAnalyticsQueryType.JourneySummary,
                            breakpoint
                        )
                        return parseJourneySummary(columns, results)
                    },
                },
            ],
            journeys: [
                [] as JourneyRow[],
                {
                    loadJourneys: async (_, breakpoint: BreakPointFunction) => {
                        const { columns, results } = await runQuery(WebAgentAnalyticsQueryType.Journeys, breakpoint)
                        return parseJourneys(columns, results)
                    },
                },
            ],
            journeyDetail: [
                [] as JourneyStep[],
                {
                    loadJourneyDetail: async (_, breakpoint: BreakPointFunction) => {
                        const { selectedJourneyKey } = values
                        if (!selectedJourneyKey) {
                            return []
                        }
                        const { columns, results } = await runQuery(
                            WebAgentAnalyticsQueryType.JourneyDetail,
                            breakpoint,
                            { journeyKey: selectedJourneyKey, limit: JOURNEY_DETAIL_LIMIT }
                        )
                        return parseJourneyDetail(columns, results)
                    },
                },
            ],
        }
    }),
    reducers({
        view: [
            'overview' as AgentView,
            {
                setView: (_, { view }) => view,
            },
        ],
        scope: [
            'live' as AgentScope,
            {
                setScope: (_, { scope }) => scope,
            },
        ],
        resultHasMore: [
            {} as Partial<Record<WebAgentAnalyticsQueryType, boolean>>,
            {
                setResultHasMore: (state, { queryType, hasMore }) =>
                    state[queryType] === hasMore ? state : { ...state, [queryType]: hasMore },
            },
        ],
        resultPages: [
            {} as Partial<Record<WebAgentAnalyticsQueryType, number>>,
            {
                refresh: () => ({}),
                setResultPage: (state, { queryType, page }) => ({ ...state, [queryType]: page }),
                setSelectedIssueKey: (state) => ({ ...state, [WebAgentAnalyticsQueryType.IssueVariants]: 1 }),
            },
        ],
        selectedIssueKey: [
            null as string | null,
            {
                setView: () => null,
                setSelectedIssueKey: (_, { key }) => key,
            },
        ],
        selectedJourneyKey: [
            null as string | null,
            {
                setView: () => null,
                setSelectedJourneyKey: (_, { journeyKey }) => journeyKey,
            },
        ],
        llmsTxtInput: [
            '',
            {
                setLlmsTxtFromUrl: (_, { content }) => content,
                submitLlmsTxtSourceFailure: () => '',
            },
        ],
        llmsTxtLoadedUrl: [
            null as string | null,
            {
                setLlmsTxtFromUrl: (_, { url }) => url,
                submitLlmsTxtSourceFailure: () => null,
            },
        ],
        llmsTxtFetchError: [
            null as string | null,
            {
                submitLlmsTxtSource: () => null,
                submitLlmsTxtSourceSuccess: () => null,
                submitLlmsTxtSourceFailure: (_, { error }) => llmsTxtFetchErrorMessage(error),
            },
        ],
        variants: [
            [] as IssueVariant[],
            {
                setSelectedIssueKey: () => [],
            },
        ],
        journeyDetail: [
            [] as JourneyStep[],
            {
                setSelectedJourneyKey: () => [],
            },
        ],
        overviewError: [
            null as string | null,
            {
                loadOverview: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.Overview),
            },
        ],
        contentGapIssuesError: [
            null as string | null,
            {
                loadIssues: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.Issues),
            },
        ],
        whatAgentsReadError: [
            null as string | null,
            {
                loadWhatAgentsRead: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.PageRequests),
            },
        ],
        nextHopsError: [
            null as string | null,
            {
                loadNextHops: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.Transitions),
            },
        ],
        demandRowsError: [
            null as string | null,
            {
                loadDemandRows: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.Demand),
            },
        ],
        variantsError: [
            null as string | null,
            {
                loadVariants: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.IssueVariants),
            },
        ],
        requestAnatomyError: [
            null as string | null,
            {
                loadRequestAnatomy: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.RequestAnatomy),
            },
        ],
        journeySummaryError: [
            null as string | null,
            {
                loadJourneySummary: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.JourneySummary),
            },
        ],
        journeysError: [
            null as string | null,
            {
                loadJourneys: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.Journeys),
            },
        ],
        journeyDetailError: [
            null as string | null,
            {
                loadJourneyDetail: () => null,
                setQueryError: errorForQuery(WebAgentAnalyticsQueryType.JourneyDetail),
            },
        ],
    }),
    selectors(({ actions }) => ({
        includeCrawlers: [(s) => [s.scope], (scope: AgentScope): boolean => scope === 'all'],
        anyLoading: [
            (s) => [
                s.overviewLoading,
                s.contentGapIssuesLoading,
                s.whatAgentsReadLoading,
                s.nextHopsLoading,
                s.demandRowsLoading,
                s.variantsLoading,
                s.requestAnatomyLoading,
                s.journeySummaryLoading,
                s.journeysLoading,
                s.journeyDetailLoading,
            ],
            (...loading: boolean[]): boolean => loading.some(Boolean),
        ],
        demandCoverage: [
            (s) => [s.demandRows, s.llmsTxtLinks],
            (demandRows: DemandRow[], llmsTxtLinks: Map<string, LlmsTxtLink>): DemandCoverage =>
                summarizeDemandCoverage(demandRows, llmsTxtLinks),
        ],
        issuesPage: [
            (s) => [s.resultPages],
            (resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>): number =>
                resultPage(resultPages, WebAgentAnalyticsQueryType.Issues),
        ],
        issues: [
            (s) => [s.contentGapIssues, s.overview, s.issuesPage],
            (contentGapIssues: AgentIssue[], overview: OverviewStats | null, issuesPage: number): AgentIssue[] =>
                [...(overview && issuesPage === 1 ? synthesizeAuxIssues(overview) : []), ...contentGapIssues].sort(
                    (a, b) => b.demand - a.demand
                ),
        ],
        topIssues: [(s) => [s.issues], (issues: AgentIssue[]): AgentIssue[] => issues.slice(0, OVERVIEW_ISSUE_COUNT)],
        selectedIssue: [
            (s) => [s.issues, s.selectedIssueKey],
            (issues: AgentIssue[], selectedIssueKey: string | null): AgentIssue | null =>
                selectedIssueKey ? (issues.find((issue) => issue.key === selectedIssueKey) ?? null) : null,
        ],
        selectedJourney: [
            (s) => [s.journeys, s.selectedJourneyKey],
            (journeys: JourneyRow[], selectedJourneyKey: string | null): JourneyRow | null =>
                selectedJourneyKey
                    ? (journeys.find((journey) => journey.journeyKey === selectedJourneyKey) ?? null)
                    : null,
        ],
        resultPaginations: [
            (s) => [s.resultPages, s.resultHasMore],
            (
                resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>,
                resultHasMore: Partial<Record<WebAgentAnalyticsQueryType, boolean>>
            ): Partial<Record<WebAgentAnalyticsQueryType, PaginationManual>> =>
                Object.fromEntries(
                    PAGINATED_QUERY_TYPES.map((queryType) => {
                        const page = resultPage(resultPages, queryType)
                        return [
                            queryType,
                            {
                                controlled: true,
                                useUrl: false,
                                currentPage: page,
                                pageSize: RESULT_PAGE_SIZE,
                                onBackward: page > 1 ? () => actions.setResultPage(queryType, page - 1) : undefined,
                                onForward: resultHasMore[queryType]
                                    ? () => actions.setResultPage(queryType, page + 1)
                                    : undefined,
                            },
                        ]
                    })
                ),
        ],
        llmsTxtLinks: [
            (s) => [s.llmsTxtInput, s.llmsTxtLoadedUrl],
            (llmsTxtInput: string, llmsTxtLoadedUrl: string | null): Map<string, LlmsTxtLink> =>
                parseLlmsTxtLinks(llmsTxtInput, llmsTxtLoadedUrl),
        ],
    })),
    listeners(({ values, actions }) => {
        const refreshResults = (): void => actions.refresh()

        const replaceSearchParams = (mutate: (params: URLSearchParams) => void): void => {
            const params = new URLSearchParams(router.values.location.search)
            mutate(params)
            const query = params.toString()
            router.actions.replace(`${router.values.location.pathname}${query ? `?${query}` : ''}`)
        }

        return {
            refresh: () => {
                const { view } = values
                if (view === 'overview') {
                    actions.loadOverview()
                    actions.loadIssues()
                    actions.loadWhatAgentsRead()
                    actions.loadJourneySummary()
                } else if (view === 'journeys') {
                    actions.loadJourneySummary()
                    actions.loadJourneys()
                    actions.loadNextHops()
                    if (values.selectedJourneyKey) {
                        actions.loadJourneyDetail()
                    }
                } else if (view === 'issues') {
                    actions.loadOverview()
                    actions.loadIssues()
                } else if (view === 'readiness') {
                    actions.loadOverview()
                    actions.loadDemandRows()
                    actions.loadRequestAnatomy()
                }
            },
            loadIssuesSuccess: () => {
                if (
                    values.selectedIssueKey &&
                    values.selectedIssue?.type === 'content_gap' &&
                    !values.variants.length
                ) {
                    actions.loadVariants()
                }
            },
            loadJourneysSuccess: () => {
                if (values.selectedJourneyKey && values.selectedJourney && !values.journeyDetail.length) {
                    actions.loadJourneyDetail()
                }
            },
            setResultPage: ({ queryType }) => {
                const reload: Partial<Record<WebAgentAnalyticsQueryType, () => void>> = {
                    [WebAgentAnalyticsQueryType.Issues]: actions.loadIssues,
                    [WebAgentAnalyticsQueryType.Transitions]: actions.loadNextHops,
                    [WebAgentAnalyticsQueryType.Demand]: actions.loadDemandRows,
                    [WebAgentAnalyticsQueryType.IssueVariants]: actions.loadVariants,
                    [WebAgentAnalyticsQueryType.RequestAnatomy]: actions.loadRequestAnatomy,
                    [WebAgentAnalyticsQueryType.Journeys]: actions.loadJourneys,
                }
                reload[queryType]?.()
            },
            setSelectedIssueKey: ({ key }) => {
                if (key && values.selectedIssue?.type === 'content_gap') {
                    actions.loadVariants()
                }
                replaceSearchParams((params) => {
                    if (key) {
                        params.set('issue', key)
                    } else {
                        params.delete('issue')
                    }
                })
            },
            setSelectedJourneyKey: ({ journeyKey }) => {
                if (journeyKey) {
                    actions.loadJourneyDetail()
                }
                replaceSearchParams((params) => {
                    if (journeyKey) {
                        params.set('journey', journeyKey)
                    } else {
                        params.delete('journey')
                    }
                })
            },
            setView: [
                ({ view }) => {
                    replaceSearchParams((params) => {
                        params.set('view', view)
                        params.delete('issue')
                        params.delete('journey')
                    })
                },
                refreshResults,
            ],
            setScope: [
                ({ scope }) => {
                    replaceSearchParams((params) => {
                        if (scope === 'all') {
                            params.set('scope', scope)
                        } else {
                            params.delete('scope')
                        }
                    })
                },
                refreshResults,
            ],
            setWebAnalyticsCompareFilter: refreshResults,
            setWebAnalyticsDateInterval: refreshResults,
            setWebAnalyticsDates: refreshResults,
            setWebAnalyticsDatesAndInterval: refreshResults,
            setWebAnalyticsFilterTestAccounts: refreshResults,
            setWebAnalyticsConversionGoal: refreshResults,
            setWebAnalyticsFilters: refreshResults,
            setWebAnalyticsDomainFilter: refreshResults,
            setWebAnalyticsDeviceTypeFilter: refreshResults,
            setWebAnalyticsCountryFilter: refreshResults,
            setWebAnalyticsReferrerFilter: refreshResults,
            setLlmsTxtFromUrl: () => actions.loadOverview(),
        }
    }),
    afterMount(({ actions }) => {
        const { view, issue, journey, scope } = router.values.searchParams
        let refreshTriggered = false
        if (scope === 'all') {
            actions.setScope(scope)
            refreshTriggered = true
        }
        const deepLinkedView: AgentView | null =
            view === 'issues' || view === 'readiness' || view === 'journeys'
                ? view
                : typeof issue === 'string' && issue
                  ? 'issues'
                  : typeof journey === 'string' && journey
                    ? 'journeys'
                    : null
        if (deepLinkedView) {
            actions.setView(deepLinkedView)
            refreshTriggered = true
        }
        if (typeof issue === 'string' && issue) {
            actions.setSelectedIssueKey(issue)
        }
        if (typeof journey === 'string' && journey) {
            actions.setSelectedJourneyKey(journey)
        }
        if (!refreshTriggered) {
            actions.refresh()
        }
    }),
])
