import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import { userEvent } from 'storybook/test'

import { FIRST_RUN_TEMPLATE_PARAM } from './firstRunGalleryLogic'
import {
    RE_ENGAGEMENT_ID,
    OWN_SENDER,
    TRIAL_UPGRADE_NUDGE_ID,
    WELCOME_SEQUENCE_ID,
    globalTemplates,
    projectThatSends,
} from './firstRunStoryFixtures'

function makeItYoursUrl(templateId: string): string {
    return `${urls.workflows()}?${FIRST_RUN_TEMPLATE_PARAM}=${templateId}`
}

const SKIP_REASON =
    'Skipping send: the domain "example.com" has no reachable mail servers, so this message would hard bounce.'

const meta: Meta = {
    component: App,
    title: 'Products/Workflows/First run make it yours',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-05',
        pageUrl: makeItYoursUrl(WELCOME_SEQUENCE_ID),
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN],
        testOptions: { viewport: { width: 1440, height: 1400 }, waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': {
                    email_sending_suspended: false,
                    email_sending_suspended_at: null,
                    email_sending_suspension_reason: '',
                },
                '/api/projects/:team_id/hog_flow_templates/': toPaginatedResponse(globalTemplates),
                '/api/projects/:team_id/integrations/': toPaginatedResponse([OWN_SENDER]),
                '/api/projects/:team_id/messaging_templates/': EMPTY_PAGINATED_RESPONSE,
            },
            post: {
                '/api/projects/:team_id/hog_flows/': [201, { id: 'wf-1', status: 'active' }],
                '/api/projects/:team_id/hog_flows/new/invocations/': [
                    200,
                    { status: 'success', logs: [], nextActionId: null },
                ],
            },
        }),
        mswDecorator(projectThatSends(['signed_up', '$pageview', '$feature_view'])),
    ],
}
export default meta

type Story = StoryObj<{}>

export const TwoEmails: Story = {}

export const ThreeEmails: Story = {
    parameters: { pageUrl: makeItYoursUrl(TRIAL_UPGRADE_NUDGE_ID) },
}

export const SingleEmail: Story = {
    parameters: { pageUrl: makeItYoursUrl(RE_ENGAGEMENT_ID) },
}

export const NoSender: Story = {
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/integrations/': EMPTY_PAGINATED_RESPONSE } })],
}

export const ViewerAccess: Story = {
    render: function ViewerAccess(): JSX.Element {
        ;(window as any).POSTHOG_APP_CONTEXT.resource_access_control.hog_flow = 'viewer'
        return <App />
    },
}

export const MemberAccess: Story = {
    render: function MemberAccess(): JSX.Element {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Member,
        })
        return <App />
    },
}

export const TestSendSkipped: Story = {
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team_id/hog_flows/new/invocations/': [
                    200,
                    {
                        status: 'success',
                        nextActionId: null,
                        logs: [{ level: 'info', timestamp: '2026-10-05T00:00:00Z', message: SKIP_REASON }],
                    },
                ],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByText('Send me a test', {}, { timeout: 15000 }))
        await canvas.findByText(/Nothing was sent/, {}, { timeout: 15000 })
    },
}

export const CreateRejected: Story = {
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team_id/hog_flows/': [
                    400,
                    {
                        type: 'validation_error',
                        code: 'invalid_input',
                        detail: 'Pick at least one event or property filter, or the trigger will never fire.',
                        attr: 'actions',
                    },
                ],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByText('Enable and open workflow', {}, { timeout: 15000 }))
        await canvas.findByText(/Couldn't create the workflow/, {}, { timeout: 15000 })
    },
}

// A docked side panel leaves the scene about 520px wide on a laptop. This viewport gives the scene the same width.
export const TwoEmailsInANarrowScene: Story = {
    parameters: { testOptions: { viewport: { width: 552, height: 2000 } } },
}
