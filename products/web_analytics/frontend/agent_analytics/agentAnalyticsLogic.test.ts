import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { performQuery } from '~/queries/query'
import { WebAgentAnalyticsQuery, WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { webAnalyticsFetchLlmsTxt } from 'products/web_analytics/frontend/generated/api'

import {
    OverviewStats,
    agentAnalyticsLogic,
    isDemandCovered,
    parseIssuesResponse,
    parseLlmsTxtLinks,
    parseOverviewRow,
    summarizeDemandCoverage,
    synthesizeAuxIssues,
} from './agentAnalyticsLogic'

jest.mock('products/web_analytics/frontend/generated/api', () => ({
    webAnalyticsFetchLlmsTxt: jest.fn(),
}))
jest.mock('~/queries/query', () => ({
    performQuery: jest.fn().mockResolvedValue({ columns: [], results: [] }),
}))

const mockFetchLlmsTxt = webAnalyticsFetchLlmsTxt as jest.Mock
const mockPerformQuery = performQuery as jest.Mock

const emptyOverview = (overrides: Partial<OverviewStats>): OverviewStats => ({
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
    ...overrides,
})

describe('agentAnalyticsLogic', () => {
    describe('parseIssuesResponse', () => {
        const columns = [
            'intent_key',
            'intent_path',
            'demand',
            'demand_prev',
            'variants',
            'top_agent',
            'first_seen',
            'last_seen',
        ]

        it('reads current and previous demand for each grouped intent', () => {
            const results = [
                [
                    'example.com/guides/token-security',
                    '/guides/token-security',
                    100,
                    80,
                    3,
                    'ChatGPT',
                    '2026-08-08 01:00:00',
                    '2026-08-14 01:00:00',
                ],
                [
                    'example.com/reference/imports',
                    '/reference/imports',
                    50,
                    0,
                    1,
                    'Claude',
                    '2026-08-11 00:00:00',
                    '2026-08-13 00:00:00',
                ],
            ]

            const issues = parseIssuesResponse(columns, results)

            expect(issues.map((issue) => issue.key)).toEqual([
                'example.com/guides/token-security',
                'example.com/reference/imports',
            ])
            const first = issues[0]
            expect(first.demand).toBe(100)
            expect(first.demandPrev).toBe(80)
            expect(first.changePct).toBe(25)
            expect(first.subtitle).toBe('3 requested URL variants')
            expect(first.topAgent).toBe('ChatGPT')
            expect(first.type).toBe('content_gap')
        })
    })

    describe('synthesizeAuxIssues', () => {
        it.each([
            [
                'waste when double-fetch waste exists',
                emptyOverview({ wasted: 120, wastePages: 9 }),
                'waste:md-twins',
                true,
            ],
            ['no waste when there is none', emptyOverview({ wasted: 0 }), 'waste:md-twins', false],
            ['malformed when present', emptyOverview({ malformed: 5 }), 'malformed:null-urls', true],
            ['no malformed when zero', emptyOverview({ malformed: 0 }), 'malformed:null-urls', false],
        ])('%s', (_name, overview, key, present) => {
            const keys = synthesizeAuxIssues(overview).map((issue) => issue.key)
            expect(keys.includes(key)).toBe(present)
        })
    })

    describe('parseLlmsTxtLinks', () => {
        it('resolves relative links against the loaded URL and preserves origin and path case', () => {
            const input = [
                '# My site',
                '- [Docs](https://example.com/docs/api/)',
                '- [Pricing](/pricing)',
                '- [Guide](Guides/Start)',
                'https://example.com/DOCS/Session-Replay',
                'not a link at all',
            ].join('\n')

            const links = parseLlmsTxtLinks(input, 'https://example.com/reference/llms.txt')

            expect(isDemandCovered({ page: '', host: 'example.com', path: '/docs/api/', demand: 1 }, links)).toBe(true)
            expect(isDemandCovered({ page: '', host: 'example.com', path: '/pricing', demand: 1 }, links)).toBe(true)
            expect(
                isDemandCovered({ page: '', host: 'example.com', path: '/reference/Guides/Start', demand: 1 }, links)
            ).toBe(true)
            expect(
                isDemandCovered({ page: '', host: 'example.com', path: '/docs/session-replay', demand: 1 }, links)
            ).toBe(false)
            expect(isDemandCovered({ page: '', host: 'other.example', path: '/pricing', demand: 1 }, links)).toBe(false)
        })

        it('treats a pasted root-relative path as applying to any host', () => {
            const links = parseLlmsTxtLinks('/pricing', null)

            expect(isDemandCovered({ page: '', host: 'other.example', path: '/pricing', demand: 1 }, links)).toBe(true)
            expect(parseLlmsTxtLinks('', null).size).toBe(0)
        })

        it('matches an appended .md representation to the original page URL', () => {
            const links = parseLlmsTxtLinks(
                '- [Libraries](https://example.com/docs/libraries.md)',
                'https://example.com/llms.txt'
            )

            expect(isDemandCovered({ page: '', host: 'example.com', path: '/docs/libraries', demand: 1 }, links)).toBe(
                true
            )
            expect(
                isDemandCovered({ page: '', host: 'example.com', path: '/docs/libraries.md', demand: 1 }, links)
            ).toBe(true)
            expect(isDemandCovered({ page: '', host: 'example.com', path: '/docs/library', demand: 1 }, links)).toBe(
                false
            )
        })

        it('reports when the file does not list any observed domains', () => {
            const links = parseLlmsTxtLinks('- [API](https://posthog.com/docs/api.md)', 'https://posthog.com/llms.txt')

            expect(
                summarizeDemandCoverage(
                    [
                        { page: 'example.com/docs/api.md', host: 'example.com', path: '/docs/api.md', demand: 75 },
                        { page: 'hedgebox.net/docs/api.md', host: 'hedgebox.net', path: '/docs/api.md', demand: 33 },
                    ],
                    links
                )
            ).toEqual({
                listedPages: 0,
                missingPages: 2,
                totalDemand: 108,
                listedDemand: 0,
                observedHosts: ['example.com', 'hedgebox.net'],
                hasMatchingHost: false,
            })
        })
    })

    describe('llms.txt URL loading', () => {
        let logic: ReturnType<typeof agentAnalyticsLogic.build>

        beforeEach(() => {
            initKeaTests()
            mockFetchLlmsTxt.mockReset()
            logic = agentAnalyticsLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('loads URL content into the coverage comparison', async () => {
            mockFetchLlmsTxt.mockResolvedValue({
                content: '# Example\n/docs\n/pricing',
                url: 'https://www.example.com/llms.txt',
            })
            logic.actions.setLlmsTxtSourceValue('url', 'https://example.com/llms.txt')

            await expectLogic(logic, () => logic.actions.submitLlmsTxtSource())
                .toFinishAllListeners()
                .toMatchValues({
                    llmsTxtInput: '# Example\n/docs\n/pricing',
                    llmsTxtLoadedUrl: 'https://www.example.com/llms.txt',
                    llmsTxtFetchError: null,
                    isLlmsTxtSourceSubmitting: false,
                })

            expect(mockFetchLlmsTxt).toHaveBeenCalledWith(expect.any(String), {
                url: 'https://example.com/llms.txt',
            })
        })

        it('shows the URL-specific server error when loading fails', async () => {
            mockFetchLlmsTxt.mockRejectedValue({ data: { url: ['The URL returned HTTP 404.'] } })
            logic.actions.setLlmsTxtSourceValue('url', 'https://example.com/missing.txt')

            await expectLogic(logic, () => logic.actions.submitLlmsTxtSource())
                .toFinishAllListeners()
                .toMatchValues({
                    llmsTxtFetchError: 'The URL returned HTTP 404.',
                    isLlmsTxtSourceSubmitting: false,
                })
        })

        it('drops the previous file when a later load fails', async () => {
            mockFetchLlmsTxt.mockResolvedValue({
                content: '# Example\n/docs\n/pricing',
                url: 'https://www.example.com/llms.txt',
            })
            logic.actions.setLlmsTxtSourceValue('url', 'https://example.com/llms.txt')
            await expectLogic(logic, () => logic.actions.submitLlmsTxtSource()).toFinishAllListeners()
            expect(logic.values.llmsTxtLinks.size).toBeGreaterThan(0)

            mockFetchLlmsTxt.mockRejectedValue({ data: { url: ['The URL returned HTTP 404.'] } })
            logic.actions.setLlmsTxtSourceValue('url', 'https://example.com/missing.txt')

            await expectLogic(logic, () => logic.actions.submitLlmsTxtSource())
                .toFinishAllListeners()
                .toMatchValues({
                    llmsTxtInput: '',
                    llmsTxtLoadedUrl: null,
                    llmsTxtFetchError: 'The URL returned HTTP 404.',
                })
            expect(logic.values.llmsTxtLinks.size).toBe(0)
        })
    })

    describe('query construction', () => {
        let logic: ReturnType<typeof agentAnalyticsLogic.build>
        let unmountWebAnalyticsLogic: (() => void) | undefined

        beforeEach(() => {
            initKeaTests()
            Object.assign(posthog, { setPersonProperties: jest.fn() })
            mockPerformQuery.mockReset().mockResolvedValue({ columns: [], results: [] })
            unmountWebAnalyticsLogic = webAnalyticsLogic.mount()
            webAnalyticsLogic.actions.setConversionGoal({ actionId: 42 })
            logic = agentAnalyticsLogic()
            logic.mount()
            mockPerformQuery.mockClear()
        })

        afterEach(() => {
            logic?.unmount()
            unmountWebAnalyticsLogic?.()
        })

        it('sends the selected goal with the overview query', async () => {
            await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()

            expect(mockPerformQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    queryType: WebAgentAnalyticsQueryType.Overview,
                    conversionGoal: { actionId: 42 },
                }),
                expect.objectContaining({ signal: expect.any(AbortSignal) })
            )
        })

        it('limits the What agents read query to five rows', async () => {
            await expectLogic(logic, () => logic.actions.loadWhatAgentsRead()).toFinishAllListeners()

            expect(mockPerformQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    queryType: WebAgentAnalyticsQueryType.PageRequests,
                    limit: 5,
                }),
                expect.objectContaining({ signal: expect.any(AbortSignal) })
            )
        })

        it.each([
            [WebAgentAnalyticsQueryType.Issues, 23],
            [WebAgentAnalyticsQueryType.Transitions, 25],
            [WebAgentAnalyticsQueryType.Demand, 25],
            [WebAgentAnalyticsQueryType.RequestAnatomy, 25],
            [WebAgentAnalyticsQueryType.Journeys, 25],
        ])('loads the next %s page from the server', async (queryType, expectedOffset) => {
            logic.actions.setResultHasMore(queryType, true)

            await expectLogic(logic, () => logic.values.resultPaginations[queryType]?.onForward?.())
                .toFinishAllListeners()
                .toMatchValues({ resultPages: { [queryType]: 2 } })

            expect(mockPerformQuery).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    queryType,
                    limit: 25,
                    offset: expectedOffset,
                }),
                expect.objectContaining({ signal: expect.any(AbortSignal) })
            )
        })

        it('keeps a failed query on its own section instead of failing the loader', async () => {
            mockPerformQuery.mockImplementation((node: WebAgentAnalyticsQuery) =>
                node.queryType === WebAgentAnalyticsQueryType.Overview
                    ? Promise.reject({ status: 500, detail: 'Query timed out' })
                    : Promise.resolve({ columns: [], results: [] })
            )

            await expectLogic(logic, () => logic.actions.loadOverview())
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['loadOverviewFailure'])
                .toMatchValues({
                    overviewError: 'Query timed out',
                    overviewLoading: false,
                    journeysError: null,
                })
        })

        it('caps journey timelines at fifty requests', async () => {
            await expectLogic(logic, () =>
                logic.actions.setSelectedJourneyKey('journey-example')
            ).toFinishAllListeners()

            expect(mockPerformQuery).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    queryType: WebAgentAnalyticsQueryType.JourneyDetail,
                    journeyKey: 'journey-example',
                    limit: 50,
                }),
                expect.objectContaining({ signal: expect.any(AbortSignal) })
            )
        })
    })

    describe('parseOverviewRow', () => {
        it('maps result columns to stats by name and defaults missing columns to zero', () => {
            const columns = [
                'active_clients',
                'server_requests',
                'client_errors',
                'converted_agents',
                'converted_agents_prev',
            ]
            const stats = parseOverviewRow(columns, [[18, 360, 35, 7, 4]])
            expect(stats.activeClients).toBe(18)
            expect(stats.serverRequests).toBe(360)
            expect(stats.clientErrors).toBe(35)
            expect(stats.convertedClients).toBe(7)
            expect(stats.convertedClientsPrev).toBe(4)
            expect(stats.wasted).toBe(0)
        })

        it('returns zeroed stats when there are no rows', () => {
            expect(parseOverviewRow([], []).activeClients).toBe(0)
        })
    })
})
