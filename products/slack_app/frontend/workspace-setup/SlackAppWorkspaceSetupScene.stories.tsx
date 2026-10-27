import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { slackAppWorkspaceSetupLogic } from './slackAppWorkspaceSetupLogic'
import { SlackAppWorkspaceSetupScene } from './SlackAppWorkspaceSetupScene'

const SETUP = {
    integration_id: 7,
    slack_workspace_name: 'Hedgebox',
    open_slack_url: 'https://slack.com/app_redirect?app=A123&team=T123',
    project_options: [],
}

const PROJECT_OPTIONS = [
    { integration_id: 7, project_name: 'Hedgebox web', organization_name: 'Hedgebox' },
    { integration_id: 8, project_name: 'Hedgebox mobile', organization_name: 'Hedgebox' },
]

function setupDecorator(response: Record<string, unknown>): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/slack_app_workspace_setup/:id/': response,
            '/api/projects/:team_id/slack_app_workspace_setup/:id/channels/': {
                channels: [
                    { id: 'C1', name: 'product', is_member: false },
                    { id: 'C2', name: 'engineering', is_member: false },
                    { id: 'C3', name: 'growth', is_member: false },
                    { id: 'C4', name: 'general', is_member: true },
                ],
            },
            '/api/organizations/@current/': { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false },
        },
    })
}

const meta: Meta<typeof SlackAppWorkspaceSetupScene> = {
    title: 'Scenes-App/Slack app/Workspace setup',
    component: SlackAppWorkspaceSetupScene,
    parameters: { layout: 'fullscreen', viewMode: 'story', mockDate: '2023-01-01' },
    render: () => (
        <BindLogic logic={slackAppWorkspaceSetupLogic} props={{ integrationId: 7 }}>
            <SlackAppWorkspaceSetupScene />
        </BindLogic>
    ),
}
export default meta

type Story = StoryObj<typeof SlackAppWorkspaceSetupScene>

export const AIConsent: Story = {
    decorators: [setupDecorator({ ...SETUP, steps: ['ai_consent'] })],
}

export const DefaultProject: Story = {
    decorators: [setupDecorator({ ...SETUP, steps: ['default_project'], project_options: PROJECT_OPTIONS })],
}

export const Channels: Story = {
    decorators: [setupDecorator({ ...SETUP, steps: ['channels'] })],
}

export const Done: Story = {
    decorators: [setupDecorator({ ...SETUP, steps: [] })],
}
