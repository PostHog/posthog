import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { SlackAppWorkspaceSettings } from './SlackAppWorkspaceSettings'

const INTEGRATIONS = {
    results: [{ id: 7, kind: 'slack', display_name: 'Hedgebox', config: {}, created_at: '2023-01-01T00:00:00Z' }],
}

const REACTION = { emoji: null, enabled: null }
const REACTIONS = { working: REACTION, done: REACTION, error: REACTION, polite: REACTION }

function settingsDecorator(
    canEditWorkspace: boolean,
    externalChannelsEnabled: boolean
): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/environments/:team_id/integrations/': INTEGRATIONS,
            '/api/projects/:team_id/integrations/': INTEGRATIONS,
            '/api/projects/:team_id/slack_app_settings/:id/': {
                integration_id: 7,
                slack_workspace_name: 'Hedgebox',
                can_edit_workspace: canEditWorkspace,
                workspace: { reactions: REACTIONS, external_channels_enabled: externalChannelsEnabled },
                personal: {
                    slack_user_id: 'U123',
                    reactions: REACTIONS,
                    effective_reactions: {
                        working: { emoji: 'eyes', enabled: true },
                        done: { emoji: 'white_check_mark', enabled: false },
                        error: { emoji: 'warning', enabled: false },
                        polite: { emoji: 'orange_heart', enabled: true },
                    },
                    default_integration_id: null,
                    project_options: [],
                    untagged_followup_mode: 'ask',
                    untagged_question_mode: 'ask',
                    thread_join_mode: 'allow',
                    auto_model_choice: false,
                    feature_tips_enabled: true,
                },
            },
        },
    })
}

const meta: Meta<typeof SlackAppWorkspaceSettings> = {
    title: 'Scenes-App/Slack app/Workspace settings',
    component: SlackAppWorkspaceSettings,
    parameters: { mockDate: '2023-01-01', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof SlackAppWorkspaceSettings>

export const Admin: Story = {
    decorators: [settingsDecorator(true, false)],
}

export const Member: Story = {
    decorators: [settingsDecorator(false, true)],
}
