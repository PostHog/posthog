import type { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    AEOKeywordApi,
    ContentAutopilotOpportunityApi,
    ContentAutopilotProposalListApi,
    ContentAutopilotRunApi,
    ContentAutopilotSiteProfileApi,
} from '../generated/api.schemas'
import { ContentAutopilot } from './ContentAutopilot'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'
import {
    type ContentAutopilotProposalTab,
    type ContentAutopilotWorkspaceTab,
    contentAutopilotLogic,
} from './contentAutopilotLogic'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import {
    EXAMPLE_ENGINE_SETTINGS,
    EXAMPLE_FAILED_DRAFT_OPPORTUNITY,
    EXAMPLE_FAILED_PROPOSAL_LIST,
    EXAMPLE_KEYWORD_MODIFIERS,
    EXAMPLE_KEYWORD_REPORT,
    EXAMPLE_KEYWORDS,
    EXAMPLE_OPPORTUNITIES,
    EXAMPLE_PROFILE,
    EXAMPLE_PROMPT_SET_CITATION_RESPONSE,
    EXAMPLE_PROMPT_SET_OVERVIEW,
    EXAMPLE_PROMPT_SET_RANKINGS,
    EXAMPLE_PROMPT_SET_SOURCES_RESPONSE,
    EXAMPLE_PROMPT_TOPICS,
    EXAMPLE_COMPETITOR_BRANDS,
    EXAMPLE_PROMPTS,
    EXAMPLE_PROMPT_CHECKS,
    EXAMPLE_PROMPT_VERSIONS,
    EXAMPLE_PROMPT_STATS,
    EXAMPLE_PROPOSAL,
    EXAMPLE_PROPOSAL_LIST,
    EXAMPLE_RUN,
    EXAMPLE_SECOND_PROFILE,
} from './contentAutopilotStoryFixtures'

const echoedFilters = (url: string): { days: number; branded: string; engine: string | null; topic: string | null } => {
    const params = new URL(url).searchParams
    return {
        days: Number(params.get('days') ?? 30),
        branded: params.get('branded') ?? 'all',
        engine: params.get('engine'),
        topic: params.get('topic'),
    }
}

// The overview's two tiles run HogQL: the daily citation rate per engine and the most cited sites.
const queryResponse = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
    const body = await request.json()
    const sql: string = body?.query?.query ?? ''
    const response = sql.includes('domain(url)')
        ? EXAMPLE_PROMPT_SET_SOURCES_RESPONSE
        : EXAMPLE_PROMPT_SET_CITATION_RESPONSE
    return [200, { ...response, hogql: sql, is_cached: true, query_status: null }]
}

const workspaceHandlers = ({
    profiles,
    runs = [],
    proposals = [],
    opportunities = [],
    keywords = EXAMPLE_KEYWORDS,
}: {
    profiles: ContentAutopilotSiteProfileApi[]
    runs?: ContentAutopilotRunApi[]
    proposals?: ContentAutopilotProposalListApi[]
    opportunities?: ContentAutopilotOpportunityApi[]
    keywords?: AEOKeywordApi[]
}): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/web_analytics_content_autopilot_profiles/': () => [
                200,
                { count: profiles.length, next: null, previous: null, results: profiles },
            ],
            '/api/projects/:team_id/web_analytics_content_autopilot_runs/': () => [
                200,
                { count: runs.length, next: null, previous: null, results: runs },
            ],
            '/api/projects/:team_id/web_analytics_content_autopilot_proposals/': () => [
                200,
                { count: proposals.length, next: null, previous: null, results: proposals },
            ],
            '/api/projects/:team_id/web_analytics_content_autopilot_proposals/:proposal_id/': () => [
                200,
                EXAMPLE_PROPOSAL,
            ],
            '/api/projects/:team_id/aeo_prompts/': () => [
                200,
                { count: EXAMPLE_PROMPTS.length, next: null, previous: null, results: EXAMPLE_PROMPTS },
            ],
            '/api/projects/:team_id/aeo_prompts/topics/': () => [200, EXAMPLE_PROMPT_TOPICS],
            // The tabs read the filters back from the response, so the mocks echo the requested ones.
            '/api/projects/:team_id/aeo_prompts/overview/': ({ request }) => [
                200,
                { ...EXAMPLE_PROMPT_SET_OVERVIEW, ...echoedFilters(request.url) },
            ],
            '/api/projects/:team_id/aeo_prompts/rankings/': ({ request }) => [
                200,
                { ...EXAMPLE_PROMPT_SET_RANKINGS, ...echoedFilters(request.url) },
            ],
            '/api/projects/:team_id/aeo_engines/': () => [200, EXAMPLE_ENGINE_SETTINGS],
            '/api/projects/:team_id/aeo_keywords/': () => [200, keywords],
            '/api/projects/:team_id/aeo_keywords/report/': ({ request }) => [
                200,
                {
                    ...EXAMPLE_KEYWORD_REPORT,
                    days: echoedFilters(request.url).days,
                    keywords: keywords.length ? EXAMPLE_KEYWORD_REPORT.keywords : [],
                },
            ],
            '/api/projects/:team_id/aeo_keywords/modifiers/': ({ request }) => [
                200,
                { ...EXAMPLE_KEYWORD_MODIFIERS, days: echoedFilters(request.url).days },
            ],
            '/api/projects/:team_id/aeo_brands/': () => [
                200,
                {
                    count: EXAMPLE_COMPETITOR_BRANDS.length,
                    next: null,
                    previous: null,
                    results: EXAMPLE_COMPETITOR_BRANDS,
                },
            ],
            '/api/projects/:team_id/aeo_prompts/:id/': () => [200, EXAMPLE_PROMPTS[0]],
            '/api/projects/:team_id/aeo_prompts/:id/stats/': () => [200, EXAMPLE_PROMPT_STATS],
            '/api/projects/:team_id/aeo_prompts/:id/versions/': () => [200, EXAMPLE_PROMPT_VERSIONS],
            '/api/projects/:team_id/aeo_prompts/:id/checks/': () => [
                200,
                { count: EXAMPLE_PROMPT_CHECKS.length, next: null, previous: null, results: EXAMPLE_PROMPT_CHECKS },
            ],
            '/api/projects/:team_id/web_analytics_content_autopilot_opportunities/': () => [
                200,
                { count: opportunities.length, next: null, previous: null, results: opportunities },
            ],
        },
        post: {
            '/api/environments/:team_id/query/:query_kind/': queryResponse,
            '/api/projects/:team_id/aeo_prompts/create_dashboard/': () => [
                201,
                { id: 1, name: 'AI visibility weekly' },
            ],
            '/api/projects/:team_id/web_analytics_content_autopilot_opportunities/refresh/': () => [200, opportunities],
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
        featureFlags: [
            FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT,
            FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT_DRAFTING,
        ],
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

export const Onboarding: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="opportunities" />
Onboarding.decorators = [workspaceHandlers({ profiles: [] })]

export const MultipleSites: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="opportunities" />
MultipleSites.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE, EXAMPLE_SECOND_PROFILE] })]

export const SiteSettings: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="settings" />
SiteSettings.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE] })]

export const ReadyForReview: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="opportunities" />
ReadyForReview.decorators = [
    workspaceHandlers({
        profiles: [EXAMPLE_PROFILE],
        runs: [EXAMPLE_RUN],
        proposals: [EXAMPLE_PROPOSAL_LIST, EXAMPLE_FAILED_PROPOSAL_LIST],
        opportunities: [...EXAMPLE_OPPORTUNITIES, EXAMPLE_FAILED_DRAFT_OPPORTUNITY],
    }),
]

export const FailedRun: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="opportunities" />
FailedRun.decorators = [
    workspaceHandlers({
        profiles: [EXAMPLE_PROFILE],
        runs: [
            {
                ...EXAMPLE_RUN,
                run_status: 'failed',
                errors: [
                    {
                        error_code: 'timed_out',
                        message: 'Drafting took too long. Try fewer opportunities at once.',
                    },
                ],
            },
        ],
    }),
]

const ProposalStory = ({ tab }: { tab?: ContentAutopilotProposalTab }): JSX.Element => {
    const { profileDataLoaded } = useValues(contentAutopilotLogic)
    const { selectProposal, setProposalTab } = useActions(contentAutopilotLogic)
    useEffect(() => {
        if (profileDataLoaded) {
            selectProposal(EXAMPLE_PROPOSAL.id)
            if (tab) {
                setProposalTab(tab)
            }
        }
    }, [profileDataLoaded, selectProposal, setProposalTab, tab])
    return (
        <div className="p-6">
            <ContentAutopilot />
        </div>
    )
}

export const ProposalReview: StoryFn<typeof ContentAutopilot> = () => <ProposalStory tab="changes" />
ProposalReview.decorators = [
    workspaceHandlers({
        profiles: [EXAMPLE_PROFILE],
        runs: [EXAMPLE_RUN],
        proposals: [EXAMPLE_PROPOSAL_LIST],
        opportunities: EXAMPLE_OPPORTUNITIES,
    }),
]

export const ActiveRun: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="drafts" />
ActiveRun.parameters = { testOptions: { waitForLoadersToDisappear: false } }
ActiveRun.decorators = [
    workspaceHandlers({
        profiles: [EXAMPLE_PROFILE],
        runs: [{ ...EXAMPLE_RUN, run_status: 'generating', completed_at: null }],
        proposals: [{ ...EXAMPLE_PROPOSAL_LIST, lifecycle_status: 'generating' }],
        opportunities: [{ ...EXAMPLE_OPPORTUNITIES[0], status: 'queued', proposal_id: null }],
    }),
]

export const DraftsTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="drafts" />
DraftsTab.decorators = [
    workspaceHandlers({
        profiles: [EXAMPLE_PROFILE],
        runs: [EXAMPLE_RUN],
        proposals: [
            { ...EXAMPLE_PROPOSAL_LIST, id: '00000000-0000-4000-8000-000000000211', lifecycle_status: 'failed' },
            EXAMPLE_PROPOSAL_LIST,
            {
                ...EXAMPLE_PROPOSAL_LIST,
                id: '00000000-0000-4000-8000-000000000212',
                proposal_type: 'new_content',
                lifecycle_status: 'exported',
                title: 'Does web analytics work without cookies?',
            },
        ],
        opportunities: EXAMPLE_OPPORTUNITIES,
    }),
]

export const ProposalPreview: StoryFn<typeof ContentAutopilot> = () => <ProposalStory />
ProposalPreview.decorators = ProposalReview.decorators

export const PromptsTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="prompts" />
PromptsTab.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE], opportunities: EXAMPLE_OPPORTUNITIES })]

export const PromptsTabNeedsImprovement: StoryFn<typeof ContentAutopilot> = () => <NeedsImprovementStory />
PromptsTabNeedsImprovement.decorators = PromptsTab.decorators

export const OverviewTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="overview" />
OverviewTab.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE], opportunities: EXAMPLE_OPPORTUNITIES })]
// The visibility chart animates as it draws, so the overview tab stays out of the snapshots.
OverviewTab.parameters = { testOptions: { snapshotBrowsers: [] } }

// A shared link carries the filters in the URL.
export const OverviewTabFiltered: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="overview" />
OverviewTabFiltered.decorators = OverviewTab.decorators
OverviewTabFiltered.parameters = {
    pageUrl: '/web/content-autopilot?days=7&engine=claude-web-search&topic=Product%20analytics',
    testOptions: { snapshotBrowsers: [] },
}

// Without the drafting flag there are no Opportunities or Drafts tabs, and no draft buttons.
export const OverviewTabWithoutDrafting: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="overview" />
OverviewTabWithoutDrafting.decorators = OverviewTab.decorators
OverviewTabWithoutDrafting.parameters = {
    featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
    testOptions: { snapshotBrowsers: [] },
}

export const RankingsTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="rankings" />
RankingsTab.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE], opportunities: EXAMPLE_OPPORTUNITIES })]

export const KeywordsTab: StoryFn<typeof ContentAutopilot> = () => <WorkspaceTabStory tab="keywords" />
KeywordsTab.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE], opportunities: EXAMPLE_OPPORTUNITIES })]

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
PromptPage.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE], opportunities: EXAMPLE_OPPORTUNITIES })]
PromptPage.parameters = { testOptions: { snapshotBrowsers: [] } }
