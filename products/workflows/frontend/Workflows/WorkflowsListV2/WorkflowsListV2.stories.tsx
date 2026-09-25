import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { FIXTURE_TEMPLATES, FIXTURE_WORKFLOWS, paginated } from './workflowsListV2Fixtures'

const workflowsUrl = (params: Record<string, string> = {}): string => {
    const search = new URLSearchParams(params).toString()
    return search ? `${urls.workflows()}?${search}` : urls.workflows()
}

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
        mswDecorator({
            get: {
                // The empty-state gate counts workflows before the scene renders.
                '/api/projects/:team_id/hog_flows/': paginated(FIXTURE_WORKFLOWS),
                '/api/projects/:team_id/hog_flows/summaries/': paginated(FIXTURE_WORKFLOWS),
                '/api/projects/:team_id/messaging_templates/summaries/': paginated(FIXTURE_TEMPLATES),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {}

export const HighlightedSends: Story = {
    parameters: { pageUrl: workflowsUrl({ q: 'from:billing@example.com' }) },
}

export const EmailTemplates: Story = {
    parameters: { pageUrl: workflowsUrl({ q: 'kind:email-template' }) },
}

export const NoMatches: Story = {
    parameters: { pageUrl: workflowsUrl({ q: 'status:active', text: 'nothing like this' }) },
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
        pageUrl: workflowsUrl({ q: 'channel:email' }),
        testOptions: { viewport: { width: 1150, height: 900 } },
    },
}

export const VeryNarrowScene: Story = {
    parameters: {
        pageUrl: workflowsUrl({ q: 'channel:email -status:archived' }),
        testOptions: { viewport: { width: 780, height: 900 } },
    },
}

export const FlagOff: Story = {
    parameters: { featureFlags: [] },
}
