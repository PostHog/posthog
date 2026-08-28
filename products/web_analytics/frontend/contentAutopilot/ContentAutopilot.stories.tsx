import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    ContentAutopilotProposalListApi,
    ContentAutopilotRunApi,
    ContentAutopilotSiteProfileApi,
} from '../generated/api.schemas'
import { ContentAutopilot } from './ContentAutopilot'
import {
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
}: {
    profiles: ContentAutopilotSiteProfileApi[]
    runs?: ContentAutopilotRunApi[]
    proposals?: ContentAutopilotProposalListApi[]
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
        },
        post: {
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

export const ReadyForReview: StoryFn<typeof ContentAutopilot> = () => (
    <div className="p-6">
        <ContentAutopilot />
    </div>
)
ReadyForReview.decorators = [
    workspaceHandlers({ profiles: [EXAMPLE_PROFILE], runs: [EXAMPLE_RUN], proposals: [EXAMPLE_PROPOSAL_LIST] }),
]

export const ActiveRun: StoryFn<typeof ContentAutopilot> = () => (
    <div className="p-6">
        <ContentAutopilot />
    </div>
)
ActiveRun.decorators = [
    workspaceHandlers({
        profiles: [EXAMPLE_PROFILE],
        runs: [{ ...EXAMPLE_RUN, run_status: 'generating', completed_at: null }],
    }),
]
