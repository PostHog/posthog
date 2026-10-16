import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { slackAppWorkspaceSetupLogic } from './slackAppWorkspaceSetupLogic'
import { SlackAppWorkspaceSetupScene } from './SlackAppWorkspaceSetupScene'

const meta: Meta<typeof SlackAppWorkspaceSetupScene> = {
    title: 'Scenes-Other/Slack app workspace setup',
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

export const Done: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/slack_app_workspace_setup/:id/': {
                    integration_id: 7,
                    slack_workspace_name: 'Hedgebox',
                    open_slack_url: 'https://slack.com/app_redirect?app=A123&team=T123',
                    steps: [],
                },
            },
        }),
    ],
}
