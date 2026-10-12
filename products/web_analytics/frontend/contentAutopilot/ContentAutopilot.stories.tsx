import type { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    ContentAutopilotOpportunityApi,
    ContentAutopilotProposalListApi,
    ContentAutopilotRunApi,
    ContentAutopilotSiteProfileApi,
} from '../generated/api.schemas'
import { ContentAutopilot } from './ContentAutopilot'
import { type ContentAutopilotProposalTab, contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'
import {
    EXAMPLE_OPPORTUNITIES,
    EXAMPLE_PROFILE,
    EXAMPLE_PROPOSAL,
    EXAMPLE_PROPOSAL_LIST,
    EXAMPLE_RUN,
    EXAMPLE_SECOND_PROFILE,
} from './contentAutopilotStoryFixtures'

const workspaceHandlers = ({
    profiles,
    runs = [],
    proposals = [],
    opportunities = [],
}: {
    profiles: ContentAutopilotSiteProfileApi[]
    runs?: ContentAutopilotRunApi[]
    proposals?: ContentAutopilotProposalListApi[]
    opportunities?: ContentAutopilotOpportunityApi[]
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
            '/api/projects/:team_id/web_analytics_content_autopilot_opportunities/': () => [
                200,
                { count: opportunities.length, next: null, previous: null, results: opportunities },
            ],
        },
        post: {
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
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE, FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
    },
}

export default meta

export const Onboarding: StoryFn<typeof ContentAutopilot> = () => (
    <div className="p-6">
        <ContentAutopilot />
    </div>
)
Onboarding.decorators = [workspaceHandlers({ profiles: [] })]

export const MultipleSites: StoryFn<typeof ContentAutopilot> = () => (
    <div className="p-6">
        <ContentAutopilot />
    </div>
)
MultipleSites.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE, EXAMPLE_SECOND_PROFILE] })]

export const SiteSettings: StoryFn<typeof ContentAutopilotSetup> = () => (
    <div className="p-6">
        <ContentAutopilotSetup />
    </div>
)
SiteSettings.decorators = [workspaceHandlers({ profiles: [EXAMPLE_PROFILE] })]

export const ReadyForReview: StoryFn<typeof ContentAutopilot> = () => (
    <div className="p-6">
        <ContentAutopilot />
    </div>
)
ReadyForReview.decorators = [
    workspaceHandlers({
        profiles: [EXAMPLE_PROFILE],
        runs: [EXAMPLE_RUN],
        proposals: [EXAMPLE_PROPOSAL_LIST],
        opportunities: EXAMPLE_OPPORTUNITIES,
    }),
]

export const ActiveRun: StoryFn<typeof ContentAutopilot> = () => (
    <div className="p-6">
        <ContentAutopilot />
    </div>
)
ActiveRun.parameters = { testOptions: { waitForLoadersToDisappear: false } }
ActiveRun.decorators = [
    workspaceHandlers({
        profiles: [EXAMPLE_PROFILE],
        runs: [{ ...EXAMPLE_RUN, run_status: 'generating', completed_at: null }],
    }),
]

export const FailedRun: StoryFn<typeof ContentAutopilot> = () => (
    <div className="p-6">
        <ContentAutopilot />
    </div>
)
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

export const DraftsTab: StoryFn<typeof ContentAutopilot> = () => {
    const { profileDataLoaded } = useValues(contentAutopilotLogic)
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    useEffect(() => {
        if (profileDataLoaded) {
            setWorkspaceTab('drafts')
        }
    }, [profileDataLoaded, setWorkspaceTab])
    return (
        <div className="p-6">
            <ContentAutopilot />
        </div>
    )
}
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
