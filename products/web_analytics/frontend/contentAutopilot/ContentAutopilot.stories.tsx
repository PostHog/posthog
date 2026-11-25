import type { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOKeywordApi, ContentAutopilotSiteProfileApi } from '../generated/api.schemas'
import { ContentAutopilot } from './ContentAutopilot'
import { type CitationsLookup, contentAutopilotCitationsModalLogic } from './contentAutopilotCitationsModalLogic'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'
import { type ContentAutopilotWorkspaceTab, contentAutopilotLogic } from './contentAutopilotLogic'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import {
    EXAMPLE_KEYWORD_MODIFIERS,
    EXAMPLE_KEYWORD_REPORT,
    EXAMPLE_KEYWORDS,
    EXAMPLE_PROFILE,
    EXAMPLE_PROMPT_SET_CITATION_RESPONSE,
    EXAMPLE_PROMPT_SET_MOVERS,
    EXAMPLE_PROMPT_SET_OVERVIEW,
    EXAMPLE_PROMPT_SET_RANKINGS,
    EXAMPLE_PROMPT_SET_SOURCES_RESPONSE,
    EXAMPLE_PROMPT_TOPICS,
    EXAMPLE_COMPETITOR_BRANDS,
    EXAMPLE_ENGINE_SETTINGS,
    EXAMPLE_PROMPTS,
    EXAMPLE_PROMPT_CHECKS,
    EXAMPLE_PROMPT_CITATIONS,
    EXAMPLE_PROMPT_VERSIONS,
    EXAMPLE_PROMPT_STATS,
    EXAMPLE_SECOND_PROFILE,
} from './contentAutopilotStoryFixtures'

const echoedFilters = (url: string): { branded: string; engine: string | null; topic: string | null } => {
    const params = new URL(url).searchParams
    return {
        branded: params.get('branded') ?? 'all',
        engine: params.get('engine'),
        topic: params.get('topic'),
    }
}

// The overview's two tiles run HogQL: the daily citation rate per engine and the most cited sites.
const queryResponse = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
    const body = await request.json()
    const sql: string = body?.query?.query ?? ''
    // The keyword report looks for a Search Console table, then reads each keyword's Google impressions from it.
    if (body?.query?.kind === 'DatabaseSchemaQuery') {
        const name = 'googlesearchconsole.search_analytics_by_query'
        return [200, { tables: { [name]: { type: 'data_warehouse', id: name, name, fields: {} } }, joins: [] }]
    }
    if (sql.includes('search_analytics_by_query')) {
        const results = EXAMPLE_KEYWORD_REPORT.keywords.map(({ keyword }, index) => [
            keyword,
            26200 - index * 4300,
            510 - index * 90,
            480 - index * 70,
            6.1 + index,
        ])
        return [200, { results, columns: ['keyword', 'impressions', 'clicks', 'searches', 'position'], hogql: sql }]
    }
    const response = sql.includes('domain(url)')
        ? EXAMPLE_PROMPT_SET_SOURCES_RESPONSE
        : EXAMPLE_PROMPT_SET_CITATION_RESPONSE
    return [200, { ...response, hogql: sql, is_cached: true, query_status: null }]
}

const workspaceHandlers = ({
    profiles,
    keywords = EXAMPLE_KEYWORDS,
}: {
    profiles: ContentAutopilotSiteProfileApi[]
    keywords?: AEOKeywordApi[]
}): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/web_analytics_content_autopilot_profiles/': () => [
                200,
                { count: profiles.length, next: null, previous: null, results: profiles },
            ],
            '/api/projects/:team_id/aeo_prompts/': () => [
                200,
                { count: EXAMPLE_PROMPTS.length, next: null, previous: null, results: EXAMPLE_PROMPTS },
            ],
            '/api/projects/:team_id/aeo_prompts/topics/': () => [200, EXAMPLE_PROMPT_TOPICS],
            '/api/projects/:team_id/aeo_prompts/citations/': () => [
                200,
                {
                    count: EXAMPLE_PROMPT_CITATIONS.length,
                    next: null,
                    previous: null,
                    results: EXAMPLE_PROMPT_CITATIONS,
                },
            ],
            // The tabs read the filters back from the response, so the mocks echo the requested ones.
            '/api/projects/:team_id/aeo_prompts/overview/': ({ request }) => [
                200,
                { ...EXAMPLE_PROMPT_SET_OVERVIEW, ...echoedFilters(request.url) },
            ],
            '/api/projects/:team_id/aeo_prompts/rankings/': ({ request }) => [
                200,
                { ...EXAMPLE_PROMPT_SET_RANKINGS, ...echoedFilters(request.url) },
            ],
            '/api/projects/:team_id/aeo_prompts/movers/': ({ request }) => [
                200,
                { ...EXAMPLE_PROMPT_SET_MOVERS, ...echoedFilters(request.url) },
            ],
            '/api/projects/:team_id/aeo_keywords/': () => [200, keywords],
            '/api/projects/:team_id/aeo_keywords/report/': () => [
                200,
                {
                    ...EXAMPLE_KEYWORD_REPORT,
                    keywords: keywords.length ? EXAMPLE_KEYWORD_REPORT.keywords : [],
                },
            ],
            '/api/projects/:team_id/aeo_keywords/modifiers/': () => [200, EXAMPLE_KEYWORD_MODIFIERS],
            '/api/projects/:team_id/aeo_brands/': () => [
                200,
                {
                    count: EXAMPLE_COMPETITOR_BRANDS.length,
                    next: null,
                    previous: null,
                    results: EXAMPLE_COMPETITOR_BRANDS,
                },
            ],
            '/api/projects/:team_id/aeo_engines/': () => [200, EXAMPLE_ENGINE_SETTINGS],
            '/api/projects/:team_id/aeo_prompts/:id/': () => [200, EXAMPLE_PROMPTS[0]],
            '/api/projects/:team_id/aeo_prompts/:id/stats/': () => [200, EXAMPLE_PROMPT_STATS],
            '/api/projects/:team_id/aeo_prompts/:id/versions/': () => [200, EXAMPLE_PROMPT_VERSIONS],
            '/api/projects/:team_id/aeo_prompts/:id/checks/': () => [
                200,
                { count: EXAMPLE_PROMPT_CHECKS.length, next: null, previous: null, results: EXAMPLE_PROMPT_CHECKS },
            ],
        },
        post: {
            '/api/environments/:team_id/query/:query_kind/': queryResponse,
            '/api/projects/:team_id/aeo_prompts/create_dashboard/': () => [
                201,
                { id: 1, name: 'AI visibility weekly' },
            ],
            '/api/projects/:team_id/web_analytics_content_autopilot_profiles/discover/': () => [
                200,
                {
                    name: 'Example docs',
                    domain: 'https://docs.example.com',
                    source_urls: ['https://docs.example.com/sitemap.xml'],
                    content_boundaries: ['/docs'],
                    sitemap_detected: true,
                    warnings: [],
                },
            ],
        },
    })

const meta: Meta<typeof ContentAutopilot> = {
    title: 'Products/Web Analytics/Content autopilot/Workspace',
    component: ContentAutopilot,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        // The fixtures carry fixed dates and the UI shows them relative to now, so the clock is pinned near them.
        mockDate: '2026-09-30',
    },
}

export default meta

const WorkspaceTabStory = ({ tab }: { tab: ContentAutopilotWorkspaceTab }): JSX.Element => {
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    useEffect(() => {
        setWorkspaceTab(tab)
    }, [setWorkspaceTab, tab])
    return (
        <div className="p-6">
            <ContentAutopilot />
        </div>
    )
}

// Needs improvement is the prompts tab's own toggle, so the date range and engine filters join the bar.
const NeedsImprovementStory = (): JSX.Element => {
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const { setEngine } = useActions(contentAutopilotFiltersLogic)
    const { setNeedsImprovement } = useActions(contentAutopilotPromptsLogic)
    useEffect(() => {
        setWorkspaceTab('prompts')
        setEngine('claude-web-search', 'prompts')
        setNeedsImprovement(true)
    }, [setWorkspaceTab, setEngine, setNeedsImprovement])
    return (
        <div className="p-6">
            <ContentAutopilot />
        </div>
    )
}

export const MultipleSites: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="settings" />
MultipleSites.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE, EXAMPLE_SECOND_PROFILE] })]

export const SiteSettings: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="settings" />
SiteSettings.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE] })]

export const PromptsTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="prompts" />
PromptsTab.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE] })]

export const PromptsTabNeedsImprovement: StoryFn<typeof ContentAutopilot> = () => <NeedsImprovementStory />
PromptsTabNeedsImprovement.decorators = PromptsTab.decorators

export const OverviewTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="overview" />
OverviewTab.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE] })]
// The visibility chart animates as it draws, so the overview tab stays out of the snapshots.
OverviewTab.parameters = { testOptions: { snapshotBrowsers: [] } }

// A shared link carries the filters in the URL.
export const OverviewTabFiltered: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="overview" />
OverviewTabFiltered.decorators = OverviewTab.decorators
OverviewTabFiltered.parameters = {
    pageUrl: '/web/content-autopilot?date_from=-7d&engine=claude-web-search&topic=Product%20analytics',
    testOptions: { snapshotBrowsers: [] },
}

export const RankingsTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="rankings" />
RankingsTab.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE] })]

export const KeywordsTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="keywords" />
KeywordsTab.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE] })]

export const KeywordsTabEmpty: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="keywords" />
KeywordsTabEmpty.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE], keywords: [] })]
KeywordsTabEmpty.parameters = { testOptions: { snapshotBrowsers: [] } }

const PromptPageStory = (): JSX.Element => {
    const { openPromptDetail } = useActions(contentAutopilotPromptDetailLogic)
    useEffect(() => {
        openPromptDetail(EXAMPLE_PROMPTS[0].id)
    }, [openPromptDetail])
    return (
        <div className="p-6">
            <ContentAutopilot />
        </div>
    )
}

export const PromptPage: StoryFn<typeof ContentAutopilot> = () => <PromptPageStory />
PromptPage.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE] })]
PromptPage.parameters = { testOptions: { snapshotBrowsers: [] } }

const CitationsStory = ({
    tab,
    lookup,
}: {
    tab: ContentAutopilotWorkspaceTab
    lookup: CitationsLookup
}): JSX.Element => {
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const { openCitations } = useActions(contentAutopilotCitationsModalLogic)
    useEffect(() => {
        setWorkspaceTab(tab)
        openCitations(lookup, 'storybook')
    }, [setWorkspaceTab, openCitations, tab, lookup])
    return (
        <div className="p-6">
            <ContentAutopilot />
        </div>
    )
}

const CITED_SITE: CitationsLookup = {
    kind: 'domain',
    value: 'analytics-review.example.com',
    dateFrom: '-30d',
    dateTo: null,
    branded: 'non_branded',
}
export const CitationsOfACitedSite: StoryFn<typeof ContentAutopilot> = () => (
    <CitationsStory tab="overview" lookup={CITED_SITE} />
)
CitationsOfACitedSite.decorators = OverviewTab.decorators
CitationsOfACitedSite.parameters = { testOptions: { snapshotBrowsers: [] } }

const OWN_PAGE: CitationsLookup = {
    kind: 'url',
    value: 'https://example.com/docs/product-analytics',
    dateFrom: '-30d',
    dateTo: null,
    branded: 'non_branded',
}
export const CitationsOfYourPage: StoryFn<typeof ContentAutopilot> = () => (
    <CitationsStory tab="rankings" lookup={OWN_PAGE} />
)
CitationsOfYourPage.decorators = OverviewTab.decorators
CitationsOfYourPage.parameters = { testOptions: { snapshotBrowsers: [] } }

const SEARCH: CitationsLookup = {
    kind: 'search',
    value: 'open source product analytics',
    dateFrom: '-30d',
    dateTo: null,
    branded: 'all',
}
export const CitationsOfASearch: StoryFn<typeof ContentAutopilot> = () => (
    <CitationsStory tab="overview" lookup={SEARCH} />
)
CitationsOfASearch.decorators = OverviewTab.decorators
CitationsOfASearch.parameters = { testOptions: { snapshotBrowsers: [] } }
