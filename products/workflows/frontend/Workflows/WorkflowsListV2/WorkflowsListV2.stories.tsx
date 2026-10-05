import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { OPTIONAL_COLUMNS } from './workflowListLabels'
import { FIXTURE_METRICS, FIXTURE_WORKFLOWS, paginated } from './workflowsListV2Fixtures'

const COLUMNS_STORAGE_KEY = 'products.workflows.frontend.workflowsListV2Logic.visibleColumns'

const workflowsUrl = (params: Record<string, string> = {}): string => {
    const search = new URLSearchParams(params).toString()
    return search ? `${urls.workflows()}?${search}` : urls.workflows()
}

const withAllColumns: NonNullable<Meta['decorators']> = [
    (Story) => {
        localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(OPTIONAL_COLUMNS))
        return <Story />
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Workflows/List v2',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-25',
        pageUrl: workflowsUrl(),
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_LIST_V2],
        testOptions: { viewport: { width: 1440, height: 900 } },
    },
    decorators: [
        // Story decorators run inside this one, so only the stories that set columns show them.
        (Story) => {
            localStorage.removeItem(COLUMNS_STORAGE_KEY)
            return <Story />
        },
        mswDecorator({
            get: {
                // The empty-state gate counts workflows before the scene renders, and the flag-off list
                // reads their steps.
                '/api/projects/:team_id/hog_flows/': paginated(
                    FIXTURE_WORKFLOWS.map((workflow) => ({ ...workflow, actions: [], edges: [] }))
                ),
                // The server search finds nothing beyond the names and descriptions the list matches itself.
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) => [
                    200,
                    paginated(new URL(request.url).searchParams.has('search') ? [] : FIXTURE_WORKFLOWS),
                ],
                '/api/projects/:team_id/hog_flows/metrics/global/': FIXTURE_METRICS,
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': {
                    email_sending_suspended: false,
                    email_sending_suspended_at: null,
                    email_sending_suspension_reason: '',
                },
                '/api/projects/:team_id/hog_flow_templates/': paginated([]),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {}

export const AllColumns: Story = {
    decorators: withAllColumns,
}

export const MetricsLoading: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        ...withAllColumns,
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/metrics/global/': () => new Promise(() => {}),
            },
        }),
    ],
}

export const MetricsUnavailable: Story = {
    decorators: [
        ...withAllColumns,
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/metrics/global/': () => [500, { detail: 'Server error' }],
            },
        }),
    ],
}

export const NoMatches: Story = {
    parameters: { pageUrl: workflowsUrl({ q: 'status:active', text: 'nothing like this' }) },
}

export const ServerSearchFailed: Story = {
    parameters: { pageUrl: workflowsUrl({ text: 'renewal' }) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) =>
                    new URL(request.url).searchParams.has('search')
                        ? [500, { detail: 'Server error' }]
                        : [200, paginated(FIXTURE_WORKFLOWS)],
            },
        }),
    ],
}

export const Loading: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => new Promise(() => {}),
            },
        }),
    ],
}

export const LoadError: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => [500, { detail: 'Server error' }],
            },
        }),
    ],
}

export const NarrowScene: Story = {
    parameters: {
        pageUrl: workflowsUrl({ q: 'type:messaging -status:archived', text: 'reminder' }),
        // The navigation collapses at this width, which leaves a 520px scene.
        testOptions: { viewport: { width: 552, height: 900 } },
    },
}

export const FlagOff: Story = {
    parameters: { featureFlags: [] },
}
