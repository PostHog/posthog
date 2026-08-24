import {
    type BreakPointFunction,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    isBreakpoint,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { router } from 'kea-router'

import type { PaginationManual } from '@posthog/lemon-ui'

import { isAbortedRequest } from 'lib/utils/requests'
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
export type JourneyConfidence = 'explicit' | 'inferred'
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
    variants: number
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
    acceptCaptured: number
    acceptMarkdownPreferred: number
    acceptMarkdownAccepted: number
    acceptHtmlOnly: number
    requestedMarkdown: number
    servedCaptured: number
    servedMarkdown: number
    retryPairs: number
    errors: number
}

export interface JourneySummary {
    totalJourneys: number
    medianPages: number
    medianRequests: number
    medianDurationSeconds: number
    journeysWithErrors: number
    explicitJourneys: number
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
    confidence: JourneyConfidence
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
    explicitJourneys: 0,
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

const RECOMMENDED_FIX: Record<AgentIssueType, string[]> = {
    content_gap: [
        'Publish a page at the requested path',
        'Redirect equivalent missing paths to the new page',
        'List the page in llms.txt and provide a markdown version',
    ],
    waste: ['List markdown versions in llms.txt', 'Advertise markdown versions with an HTTP Link header'],
    malformed: ['Redirect each malformed path to the closest valid page'],
}

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
            const demand = num(row[demandIdx])
            const demandPrev = num(row[demandPrevIdx])
            const variants = num(row[variantsIdx])
            return {
                key,
                type: 'content_gap',
                title: `Agents requested ${str(row[pathIdx]) || '(unknown page)'}`,
                subtitle: `${variants} requested URL ${variants === 1 ? 'variant' : 'variants'}`,
                demand,
                demandPrev,
                changePct: changePct(demand, demandPrev),
                variants,
                topAgent: str(row[agentIdx]) || null,
                firstSeen: str(row[firstSeenIdx]) || null,
                lastSeen: str(row[lastSeenIdx]) || null,
                recommendedFix: RECOMMENDED_FIX.content_gap,
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
            variants: overview.wastePages,
            topAgent: null,
            firstSeen: null,
            lastSeen: null,
            recommendedFix: RECOMMENDED_FIX.waste,
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
            variants: 0,
            topAgent: null,
            firstSeen: null,
            lastSeen: null,
            recommendedFix: RECOMMENDED_FIX.malformed,
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
    const acceptCapturedIdx = columnIndex(columns, 'accept_captured')
    const acceptPreferredIdx = columnIndex(columns, 'accept_markdown_preferred')
    const acceptAcceptedIdx = columnIndex(columns, 'accept_markdown_accepted')
    const acceptHtmlIdx = columnIndex(columns, 'accept_html_only')
    const requestedMdIdx = columnIndex(columns, 'requested_markdown')
    const servedCapturedIdx = columnIndex(columns, 'served_captured')
    const servedMdIdx = columnIndex(columns, 'served_markdown')
    const retryIdx = columnIndex(columns, 'retry_pairs')
    const errorsIdx = columnIndex(columns, 'errors')
    return (results ?? []).filter(Array.isArray).map((row) => ({
        agent: str(row[agentIdx]) || 'Unclassified agent',
        requests: num(row[requestsIdx]),
        acceptCaptured: num(row[acceptCapturedIdx]),
        acceptMarkdownPreferred: num(row[acceptPreferredIdx]),
        acceptMarkdownAccepted: num(row[acceptAcceptedIdx]),
        acceptHtmlOnly: num(row[acceptHtmlIdx]),
        requestedMarkdown: num(row[requestedMdIdx]),
        servedCaptured: num(row[servedCapturedIdx]),
        servedMarkdown: num(row[servedMdIdx]),
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
        explicitJourneys: get('explicit_journeys'),
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
    const confidenceIdx = columnIndex(columns, 'confidence')
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
                confidence: str(row[confidenceIdx]) === 'explicit' ? 'explicit' : 'inferred',
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

export interface agentAnalyticsLogicValues {
    currentTeam: TeamPublicType | TeamType | null
    dateFilter: DateFilterState
    filterTestAccounts: boolean
    compareFilter: CompareFilter
    conversionGoal: WebAnalyticsConversionGoal | null
    webAnalyticsFilters: WebAnalyticsPropertyFilters
    view: AgentView
    scope: AgentScope
    contentGrouping: WebAgentContentGrouping
    resultHasMore: Partial<Record<WebAgentAnalyticsQueryType, boolean>>
    selectedIssueKey: string | null
    llmsTxtInput: string
    llmsTxtSource: LlmsTxtSourceForm
    llmsTxtSourceAllErrors: Record<string, any>
    llmsTxtSourceChanged: boolean
    llmsTxtSourceErrors: DeepPartialMap<LlmsTxtSourceForm, ValidationErrorType>
    llmsTxtSourceHasErrors: boolean
    llmsTxtSourceManualErrors: Record<string, any>
    llmsTxtSourceTouched: boolean
    llmsTxtSourceTouches: Record<string, boolean>
    llmsTxtSourceValidationErrors: DeepPartialMap<LlmsTxtSourceForm, ValidationErrorType>
    llmsTxtLoadedUrl: string | null
    llmsTxtFetchError: string | null
    isLlmsTxtSourceSubmitting: boolean
    isLlmsTxtSourceValid: boolean
    showLlmsTxtSourceErrors: boolean
    overview: OverviewStats | null
    overviewLoading: boolean
    overviewError: string | null
    contentGapIssues: AgentIssue[]
    issuesLoading: boolean
    issuesError: string | null
    whatAgentsRead: PageRead[]
    whatAgentsReadLoading: boolean
    whatAgentsReadError: string | null
    nextHops: NextHop[]
    nextHopsLoading: boolean
    nextHopsError: string | null
    demandRows: DemandRow[]
    demandRowsLoading: boolean
    demandRowsError: string | null
    variants: IssueVariant[]
    variantsLoading: boolean
    variantsError: string | null
    requestAnatomy: RequestAnatomyRow[]
    requestAnatomyLoading: boolean
    requestAnatomyError: string | null
    journeySummary: JourneySummary | null
    journeySummaryLoading: boolean
    journeySummaryError: string | null
    journeys: JourneyRow[]
    journeysLoading: boolean
    journeysError: string | null
    resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>
    resultPaginations: Partial<Record<WebAgentAnalyticsQueryType, PaginationManual>>
    selectedJourneyKey: string | null
    journeyDetail: JourneyStep[]
    journeyDetailLoading: boolean
    journeyDetailError: string | null
    includeCrawlers: boolean
    anyLoading: boolean
    issues: AgentIssue[]
    topIssues: AgentIssue[]
    selectedIssue: AgentIssue | null
    selectedJourney: JourneyRow | null
    llmsTxtLinks: Map<string, LlmsTxtLink>
    demandCoverage: DemandCoverage
}

export interface agentAnalyticsLogicActions {
    setWebAnalyticsCompareFilter: (compareFilter: CompareFilter) => { compareFilter: CompareFilter }
    setWebAnalyticsDateInterval: (interval: IntervalType) => { interval: IntervalType }
    setWebAnalyticsDates: (
        dateFrom: string | null,
        dateTo: string | null
    ) => { dateFrom: string | null; dateTo: string | null }
    setWebAnalyticsDatesAndInterval: (
        dateFrom: string | null,
        dateTo: string | null,
        interval: IntervalType
    ) => { dateFrom: string | null; dateTo: string | null; interval: IntervalType }
    setWebAnalyticsFilterTestAccounts: (shouldFilterTestAccounts: boolean) => { shouldFilterTestAccounts: boolean }
    setWebAnalyticsConversionGoal: (conversionGoal: WebAnalyticsConversionGoal | null) => {
        conversionGoal: WebAnalyticsConversionGoal | null
    }
    setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
        webAnalyticsFilters: WebAnalyticsPropertyFilters
    }
    setWebAnalyticsDomainFilter: (domain: string | null) => { domain: string | null }
    setWebAnalyticsDeviceTypeFilter: (deviceType: 'Desktop' | 'Mobile' | null) => {
        deviceType: 'Desktop' | 'Mobile' | null
    }
    setWebAnalyticsCountryFilter: (countryCode: string | null) => { countryCode: string | null }
    setWebAnalyticsReferrerFilter: (referrer: string | null) => { referrer: string | null }
    setView: (view: AgentView) => { view: AgentView }
    setScope: (scope: AgentScope) => { scope: AgentScope }
    setSelectedJourneyKey: (journeyKey: string | null) => { journeyKey: string | null }
    setContentGrouping: (contentGrouping: WebAgentContentGrouping) => { contentGrouping: WebAgentContentGrouping }
    setResultHasMore: (
        queryType: WebAgentAnalyticsQueryType,
        hasMore: boolean
    ) => {
        queryType: WebAgentAnalyticsQueryType
        hasMore: boolean
    }
    setSelectedIssueKey: (key: string | null) => { key: string | null }
    setLlmsTxtFromUrl: (content: string, url: string) => { content: string; url: string }
    resetLlmsTxtSource: (values?: LlmsTxtSourceForm) => { values?: LlmsTxtSourceForm }
    setLlmsTxtSourceManualErrors: (errors: Record<string, any>) => { errors: Record<string, any> }
    setLlmsTxtSourceValue: (key: FieldName, value: any) => { name: FieldName; value: any }
    setLlmsTxtSourceValues: (values: DeepPartial<LlmsTxtSourceForm>) => { values: DeepPartial<LlmsTxtSourceForm> }
    submitLlmsTxtSource: () => { value: boolean }
    submitLlmsTxtSourceFailure: (
        error: Error,
        errors: Record<string, any>
    ) => { error: Error; errors: Record<string, any> }
    submitLlmsTxtSourceRequest: (llmsTxtSource: LlmsTxtSourceForm) => { llmsTxtSource: LlmsTxtSourceForm }
    submitLlmsTxtSourceSuccess: (llmsTxtSource: LlmsTxtSourceForm) => { llmsTxtSource: LlmsTxtSourceForm }
    touchLlmsTxtSourceField: (key: string) => { key: string }
    refresh: () => { value: true }
    loadOverview: () => { value: true }
    loadOverviewSuccess: (overview: OverviewStats) => { overview: OverviewStats }
    loadOverviewFailure: (error: string) => { error: string }
    loadIssues: () => { value: true }
    loadIssuesSuccess: (contentGapIssues: AgentIssue[]) => { contentGapIssues: AgentIssue[] }
    loadIssuesFailure: (error: string) => { error: string }
    loadWhatAgentsRead: () => { value: true }
    loadWhatAgentsReadSuccess: (whatAgentsRead: PageRead[]) => { whatAgentsRead: PageRead[] }
    loadWhatAgentsReadFailure: (error: string) => { error: string }
    loadNextHops: () => { value: true }
    loadNextHopsSuccess: (nextHops: NextHop[]) => { nextHops: NextHop[] }
    loadNextHopsFailure: (error: string) => { error: string }
    loadDemandRows: () => { value: true }
    loadDemandRowsSuccess: (demandRows: DemandRow[]) => { demandRows: DemandRow[] }
    loadDemandRowsFailure: (error: string) => { error: string }
    loadVariants: () => { value: true }
    loadVariantsSuccess: (variants: IssueVariant[]) => { variants: IssueVariant[] }
    loadVariantsFailure: (error: string) => { error: string }
    loadRequestAnatomy: () => { value: true }
    loadRequestAnatomySuccess: (requestAnatomy: RequestAnatomyRow[]) => { requestAnatomy: RequestAnatomyRow[] }
    loadRequestAnatomyFailure: (error: string) => { error: string }
    loadJourneySummary: () => { value: true }
    loadJourneySummarySuccess: (journeySummary: JourneySummary) => { journeySummary: JourneySummary }
    loadJourneySummaryFailure: (error: string) => { error: string }
    loadJourneys: () => { value: true }
    loadJourneysSuccess: (journeys: JourneyRow[]) => { journeys: JourneyRow[] }
    loadJourneysFailure: (error: string) => { error: string }
    setResultPage: (
        queryType: WebAgentAnalyticsQueryType,
        page: number
    ) => {
        queryType: WebAgentAnalyticsQueryType
        page: number
    }
    loadJourneyDetail: () => { value: true }
    loadJourneyDetailSuccess: (journeyDetail: JourneyStep[]) => { journeyDetail: JourneyStep[] }
    loadJourneyDetailFailure: (error: string) => { error: string }
}

export type agentAnalyticsLogicType = MakeLogicType<agentAnalyticsLogicValues, agentAnalyticsLogicActions>

const OVERVIEW_ISSUE_COUNT = 4
const WHAT_AGENTS_READ_LIMIT = 5
const RESULT_PAGE_SIZE = 25
const FIRST_PAGE_ISSUE_RESULT_LIMIT = RESULT_PAGE_SIZE - 2
const JOURNEY_DETAIL_LIMIT = 50

const PAGINATED_QUERY_TYPES = [
    WebAgentAnalyticsQueryType.Issues,
    WebAgentAnalyticsQueryType.Transitions,
    WebAgentAnalyticsQueryType.Demand,
    WebAgentAnalyticsQueryType.IssueVariants,
    WebAgentAnalyticsQueryType.RequestAnatomy,
    WebAgentAnalyticsQueryType.Journeys,
] as const

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
        setContentGrouping: (contentGrouping: WebAgentContentGrouping) => ({ contentGrouping }),
        setResultHasMore: (queryType: WebAgentAnalyticsQueryType, hasMore: boolean) => ({ queryType, hasMore }),
        setResultPage: (queryType: WebAgentAnalyticsQueryType, page: number) => ({ queryType, page }),
        setSelectedIssueKey: (key: string | null) => ({ key }),
        setLlmsTxtFromUrl: (content: string, url: string) => ({ content, url }),
        refresh: true,
        loadOverview: true,
        loadOverviewSuccess: (overview: OverviewStats) => ({ overview }),
        loadOverviewFailure: (error: string) => ({ error }),
        loadIssues: true,
        loadIssuesSuccess: (contentGapIssues: AgentIssue[]) => ({ contentGapIssues }),
        loadIssuesFailure: (error: string) => ({ error }),
        loadWhatAgentsRead: true,
        loadWhatAgentsReadSuccess: (whatAgentsRead: PageRead[]) => ({ whatAgentsRead }),
        loadWhatAgentsReadFailure: (error: string) => ({ error }),
        loadNextHops: true,
        loadNextHopsSuccess: (nextHops: NextHop[]) => ({ nextHops }),
        loadNextHopsFailure: (error: string) => ({ error }),
        loadDemandRows: true,
        loadDemandRowsSuccess: (demandRows: DemandRow[]) => ({ demandRows }),
        loadDemandRowsFailure: (error: string) => ({ error }),
        loadVariants: true,
        loadVariantsSuccess: (variants: IssueVariant[]) => ({ variants }),
        loadVariantsFailure: (error: string) => ({ error }),
        loadRequestAnatomy: true,
        loadRequestAnatomySuccess: (requestAnatomy: RequestAnatomyRow[]) => ({ requestAnatomy }),
        loadRequestAnatomyFailure: (error: string) => ({ error }),
        loadJourneySummary: true,
        loadJourneySummarySuccess: (journeySummary: JourneySummary) => ({ journeySummary }),
        loadJourneySummaryFailure: (error: string) => ({ error }),
        loadJourneys: true,
        loadJourneysSuccess: (journeys: JourneyRow[]) => ({ journeys }),
        loadJourneysFailure: (error: string) => ({ error }),
        loadJourneyDetail: true,
        loadJourneyDetailSuccess: (journeyDetail: JourneyStep[]) => ({ journeyDetail }),
        loadJourneyDetailFailure: (error: string) => ({ error }),
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
        contentGrouping: [
            WebAgentContentGrouping.Normalized,
            {
                setContentGrouping: (_, { contentGrouping }) => contentGrouping,
            },
        ],
        resultHasMore: [
            {} as Partial<Record<WebAgentAnalyticsQueryType, boolean>>,
            {
                setResultHasMore: (state, { queryType, hasMore }) => ({ ...state, [queryType]: hasMore }),
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
            },
        ],
        llmsTxtLoadedUrl: [
            null as string | null,
            {
                submitLlmsTxtSource: () => null,
                setLlmsTxtFromUrl: (_, { url }) => url,
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
        overview: [
            null as OverviewStats | null,
            {
                loadOverview: () => null,
                loadOverviewSuccess: (_, { overview }) => overview,
            },
        ],
        overviewLoading: [
            false,
            {
                loadOverview: () => true,
                loadOverviewSuccess: () => false,
                loadOverviewFailure: () => false,
            },
        ],
        overviewError: [
            null as string | null,
            {
                loadOverview: () => null,
                loadOverviewFailure: (_, { error }) => error,
            },
        ],
        contentGapIssues: [
            [] as AgentIssue[],
            {
                loadIssues: () => [],
                loadIssuesSuccess: (_, { contentGapIssues }) => contentGapIssues,
            },
        ],
        issuesLoading: [
            false,
            {
                loadIssues: () => true,
                loadIssuesSuccess: () => false,
                loadIssuesFailure: () => false,
            },
        ],
        issuesError: [
            null as string | null,
            {
                loadIssues: () => null,
                loadIssuesFailure: (_, { error }) => error,
            },
        ],
        whatAgentsRead: [
            [] as PageRead[],
            {
                loadWhatAgentsReadSuccess: (_, { whatAgentsRead }) => whatAgentsRead,
            },
        ],
        whatAgentsReadLoading: [
            false,
            {
                loadWhatAgentsRead: () => true,
                loadWhatAgentsReadSuccess: () => false,
                loadWhatAgentsReadFailure: () => false,
            },
        ],
        whatAgentsReadError: [
            null as string | null,
            {
                loadWhatAgentsRead: () => null,
                loadWhatAgentsReadFailure: (_, { error }) => error,
            },
        ],
        nextHops: [
            [] as NextHop[],
            {
                loadNextHopsSuccess: (_, { nextHops }) => nextHops,
            },
        ],
        nextHopsLoading: [
            false,
            {
                loadNextHops: () => true,
                loadNextHopsSuccess: () => false,
                loadNextHopsFailure: () => false,
            },
        ],
        nextHopsError: [
            null as string | null,
            {
                loadNextHops: () => null,
                loadNextHopsFailure: (_, { error }) => error,
            },
        ],
        demandRows: [
            [] as DemandRow[],
            {
                loadDemandRowsSuccess: (_, { demandRows }) => demandRows,
            },
        ],
        demandRowsLoading: [
            false,
            {
                loadDemandRows: () => true,
                loadDemandRowsSuccess: () => false,
                loadDemandRowsFailure: () => false,
            },
        ],
        demandRowsError: [
            null as string | null,
            {
                loadDemandRows: () => null,
                loadDemandRowsFailure: (_, { error }) => error,
            },
        ],
        variants: [
            [] as IssueVariant[],
            {
                setSelectedIssueKey: () => [],
                loadVariants: () => [],
                loadVariantsSuccess: (_, { variants }) => variants,
            },
        ],
        variantsLoading: [
            false,
            {
                loadVariants: () => true,
                loadVariantsSuccess: () => false,
                loadVariantsFailure: () => false,
            },
        ],
        variantsError: [
            null as string | null,
            {
                loadVariants: () => null,
                loadVariantsFailure: (_, { error }) => error,
            },
        ],
        requestAnatomy: [
            [] as RequestAnatomyRow[],
            {
                loadRequestAnatomySuccess: (_, { requestAnatomy }) => requestAnatomy,
            },
        ],
        requestAnatomyLoading: [
            false,
            {
                loadRequestAnatomy: () => true,
                loadRequestAnatomySuccess: () => false,
                loadRequestAnatomyFailure: () => false,
            },
        ],
        requestAnatomyError: [
            null as string | null,
            {
                loadRequestAnatomy: () => null,
                loadRequestAnatomyFailure: (_, { error }) => error,
            },
        ],
        journeySummary: [
            null as JourneySummary | null,
            {
                loadJourneySummarySuccess: (_, { journeySummary }) => journeySummary,
            },
        ],
        journeySummaryLoading: [
            false,
            {
                loadJourneySummary: () => true,
                loadJourneySummarySuccess: () => false,
                loadJourneySummaryFailure: () => false,
            },
        ],
        journeySummaryError: [
            null as string | null,
            {
                loadJourneySummary: () => null,
                loadJourneySummaryFailure: (_, { error }) => error,
            },
        ],
        journeys: [
            [] as JourneyRow[],
            {
                loadJourneysSuccess: (_, { journeys }) => journeys,
            },
        ],
        journeysLoading: [
            false,
            {
                loadJourneys: () => true,
                loadJourneysSuccess: () => false,
                loadJourneysFailure: () => false,
            },
        ],
        journeysError: [
            null as string | null,
            {
                loadJourneys: () => null,
                loadJourneysFailure: (_, { error }) => error,
            },
        ],
        journeyDetail: [
            [] as JourneyStep[],
            {
                setSelectedJourneyKey: () => [],
                loadJourneyDetail: () => [],
                loadJourneyDetailSuccess: (_, { journeyDetail }) => journeyDetail,
            },
        ],
        journeyDetailLoading: [
            false,
            {
                loadJourneyDetail: () => true,
                loadJourneyDetailSuccess: () => false,
                loadJourneyDetailFailure: () => false,
            },
        ],
        journeyDetailError: [
            null as string | null,
            {
                loadJourneyDetail: () => null,
                loadJourneyDetailFailure: (_, { error }) => error,
            },
        ],
    }),
    selectors(({ actions }) => ({
        includeCrawlers: [(s) => [s.scope], (scope: AgentScope): boolean => scope === 'all'],
        anyLoading: [
            (s) => [
                s.overviewLoading,
                s.issuesLoading,
                s.whatAgentsReadLoading,
                s.nextHopsLoading,
                s.demandRowsLoading,
                s.variantsLoading,
                s.requestAnatomyLoading,
                s.journeySummaryLoading,
                s.journeysLoading,
                s.journeyDetailLoading,
            ],
            (
                overviewLoading: boolean,
                issuesLoading: boolean,
                whatAgentsReadLoading: boolean,
                nextHopsLoading: boolean,
                demandRowsLoading: boolean,
                variantsLoading: boolean,
                requestAnatomyLoading: boolean,
                journeySummaryLoading: boolean,
                journeysLoading: boolean,
                journeyDetailLoading: boolean
            ): boolean =>
                overviewLoading ||
                issuesLoading ||
                whatAgentsReadLoading ||
                nextHopsLoading ||
                demandRowsLoading ||
                variantsLoading ||
                requestAnatomyLoading ||
                journeySummaryLoading ||
                journeysLoading ||
                journeyDetailLoading,
        ],
        demandCoverage: [
            (s) => [s.demandRows, s.llmsTxtLinks],
            (demandRows: DemandRow[], llmsTxtLinks: Map<string, LlmsTxtLink>): DemandCoverage =>
                summarizeDemandCoverage(demandRows, llmsTxtLinks),
        ],
        issues: [
            (s) => [s.contentGapIssues, s.overview, s.resultPages],
            (
                contentGapIssues: AgentIssue[],
                overview: OverviewStats | null,
                resultPages: Partial<Record<WebAgentAnalyticsQueryType, number>>
            ): AgentIssue[] =>
                [
                    ...(overview && resultPage(resultPages, WebAgentAnalyticsQueryType.Issues) === 1
                        ? synthesizeAuxIssues(overview)
                        : []),
                    ...contentGapIssues,
                ].sort((a, b) => b.demand - a.demand),
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
    listeners(({ values, actions, cache }) => {
        const refreshResults = (): void => actions.refresh()
        const signalFor = (key: string): AbortSignal => {
            const abortController = new AbortController()
            cache.disposables.add(() => () => abortController.abort(), key, { pauseOnPageHidden: false })
            return abortController.signal
        }
        const isCancellation = (error: unknown): boolean =>
            (error instanceof Error && isBreakpoint(error)) || isAbortedRequest(error)
        const failureMessage = (error: unknown): string =>
            error instanceof Error ? error.message : 'Could not load agent analytics'

        const runQuery = async (
            queryType: WebAgentAnalyticsQueryType,
            signal: AbortSignal,
            opts: QueryOptions = {}
        ): Promise<{ columns?: string[]; results?: unknown[][]; hasMore: boolean }> => {
            const node: WebAgentAnalyticsQuery = {
                kind: NodeKind.WebAgentAnalyticsQuery,
                queryType,
                includeCrawlers: values.includeCrawlers,
                contentGrouping: values.contentGrouping,
                llmsTxtUrl: values.llmsTxtLoadedUrl ?? undefined,
                limit:
                    opts.limit ??
                    (queryType === WebAgentAnalyticsQueryType.PageRequests ? WHAT_AGENTS_READ_LIMIT : undefined),
                offset: opts.offset,
                intentKey: opts.intentKey,
                journeyKey: opts.journeyKey,
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
            const response = await performQuery(node, { signal })
            return {
                columns: response.columns as string[] | undefined,
                results: response.results as unknown[][] | undefined,
                hasMore: response.hasMore ?? false,
            }
        }

        const makeQueryLoader =
            (
                queryType: WebAgentAnalyticsQueryType,
                signalKey: string,
                onSuccess: (columns: string[] | undefined, results: unknown[][] | undefined) => void,
                onFailure: (error: string) => void,
                tracksHasMore: boolean = true,
                queryOptions: () => QueryOptions = () => ({})
            ) =>
            async (_: unknown, breakpoint: BreakPointFunction): Promise<void> => {
                await breakpoint(300)
                const signal = signalFor(signalKey)
                try {
                    const { columns, results, hasMore } = await runQuery(queryType, signal, queryOptions())
                    breakpoint()
                    if (tracksHasMore) {
                        actions.setResultHasMore(queryType, hasMore)
                    }
                    onSuccess(columns, results)
                } catch (error) {
                    if (isCancellation(error)) {
                        return
                    }
                    onFailure(failureMessage(error))
                }
            }

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
            loadOverview: makeQueryLoader(
                WebAgentAnalyticsQueryType.Overview,
                'overview',
                (columns, results) => actions.loadOverviewSuccess(parseOverviewRow(columns, results)),
                actions.loadOverviewFailure,
                false
            ),
            loadIssues: makeQueryLoader(
                WebAgentAnalyticsQueryType.Issues,
                'issues',
                (columns, results) => actions.loadIssuesSuccess(parseIssuesResponse(columns, results)),
                actions.loadIssuesFailure,
                true,
                () => paginatedQueryOptions(values.resultPages, WebAgentAnalyticsQueryType.Issues)
            ),
            loadIssuesSuccess: () => {
                if (
                    values.selectedIssueKey &&
                    values.selectedIssue?.type === 'content_gap' &&
                    !values.variants.length
                ) {
                    actions.loadVariants()
                }
            },
            loadWhatAgentsRead: makeQueryLoader(
                WebAgentAnalyticsQueryType.PageRequests,
                'whatAgentsRead',
                (columns, results) => actions.loadWhatAgentsReadSuccess(parseWhatAgentsRead(columns, results)),
                actions.loadWhatAgentsReadFailure,
                false
            ),
            loadNextHops: makeQueryLoader(
                WebAgentAnalyticsQueryType.Transitions,
                'nextHops',
                (columns, results) => actions.loadNextHopsSuccess(parseNextHops(columns, results)),
                actions.loadNextHopsFailure,
                true,
                () => paginatedQueryOptions(values.resultPages, WebAgentAnalyticsQueryType.Transitions)
            ),
            loadDemandRows: makeQueryLoader(
                WebAgentAnalyticsQueryType.Demand,
                'demandRows',
                (columns, results) => actions.loadDemandRowsSuccess(parseDemandRows(columns, results)),
                actions.loadDemandRowsFailure,
                true,
                () => paginatedQueryOptions(values.resultPages, WebAgentAnalyticsQueryType.Demand)
            ),
            loadRequestAnatomy: makeQueryLoader(
                WebAgentAnalyticsQueryType.RequestAnatomy,
                'requestAnatomy',
                (columns, results) => actions.loadRequestAnatomySuccess(parseRequestAnatomy(columns, results)),
                actions.loadRequestAnatomyFailure,
                true,
                () => paginatedQueryOptions(values.resultPages, WebAgentAnalyticsQueryType.RequestAnatomy)
            ),
            loadJourneySummary: makeQueryLoader(
                WebAgentAnalyticsQueryType.JourneySummary,
                'journeySummary',
                (columns, results) => actions.loadJourneySummarySuccess(parseJourneySummary(columns, results)),
                actions.loadJourneySummaryFailure,
                false
            ),
            loadJourneys: makeQueryLoader(
                WebAgentAnalyticsQueryType.Journeys,
                'journeys',
                (columns, results) => actions.loadJourneysSuccess(parseJourneys(columns, results)),
                actions.loadJourneysFailure,
                true,
                () => paginatedQueryOptions(values.resultPages, WebAgentAnalyticsQueryType.Journeys)
            ),
            setResultPage: ({ queryType }) => {
                switch (queryType) {
                    case WebAgentAnalyticsQueryType.Issues:
                        actions.loadIssues()
                        break
                    case WebAgentAnalyticsQueryType.Transitions:
                        actions.loadNextHops()
                        break
                    case WebAgentAnalyticsQueryType.Demand:
                        actions.loadDemandRows()
                        break
                    case WebAgentAnalyticsQueryType.IssueVariants:
                        actions.loadVariants()
                        break
                    case WebAgentAnalyticsQueryType.RequestAnatomy:
                        actions.loadRequestAnatomy()
                        break
                    case WebAgentAnalyticsQueryType.Journeys:
                        actions.loadJourneys()
                        break
                }
            },
            loadJourneysSuccess: () => {
                if (values.selectedJourneyKey && values.selectedJourney && !values.journeyDetail.length) {
                    actions.loadJourneyDetail()
                }
            },
            loadJourneyDetail: async (_, breakpoint) => {
                await breakpoint(300)
                const { selectedJourneyKey } = values
                if (!selectedJourneyKey) {
                    return
                }
                const signal = signalFor('journeyDetail')
                try {
                    const { columns, results } = await runQuery(WebAgentAnalyticsQueryType.JourneyDetail, signal, {
                        journeyKey: selectedJourneyKey,
                        limit: JOURNEY_DETAIL_LIMIT,
                    })
                    breakpoint()
                    actions.loadJourneyDetailSuccess(parseJourneyDetail(columns, results))
                } catch (error) {
                    if (isCancellation(error)) {
                        return
                    }
                    actions.loadJourneyDetailFailure(failureMessage(error))
                }
            },
            loadVariants: async (_, breakpoint) => {
                await breakpoint(300)
                const { selectedIssueKey, selectedIssue } = values
                if (!selectedIssueKey || selectedIssue?.type !== 'content_gap') {
                    return
                }
                const signal = signalFor('variants')
                try {
                    const { columns, results, hasMore } = await runQuery(
                        WebAgentAnalyticsQueryType.IssueVariants,
                        signal,
                        {
                            intentKey: selectedIssueKey,
                            ...paginatedQueryOptions(values.resultPages, WebAgentAnalyticsQueryType.IssueVariants),
                        }
                    )
                    breakpoint()
                    actions.setResultHasMore(WebAgentAnalyticsQueryType.IssueVariants, hasMore)
                    actions.loadVariantsSuccess(parseVariants(columns, results))
                } catch (error) {
                    if (isCancellation(error)) {
                        return
                    }
                    actions.loadVariantsFailure(failureMessage(error))
                }
            },
            setSelectedIssueKey: ({ key }) => {
                if (key) {
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
            setContentGrouping: refreshResults,
            setLlmsTxtFromUrl: refreshResults,
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
