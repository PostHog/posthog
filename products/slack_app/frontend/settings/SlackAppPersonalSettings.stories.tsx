import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { SlackAppPersonalSettings } from './SlackAppPersonalSettings'

const INTEGRATIONS = {
    results: [{ id: 7, kind: 'slack', display_name: 'Hedgebox', config: {}, created_at: '2023-01-01T00:00:00Z' }],
}

const REACTION = { emoji: null, enabled: null }
const REACTIONS = { working: REACTION, done: REACTION, error: REACTION, polite: REACTION }

const PERSONAL = {
    slack_user_id: 'U123',
    reactions: REACTIONS,
    effective_reactions: {
        working: { emoji: 'eyes', enabled: true },
        done: { emoji: 'white_check_mark', enabled: false },
        error: { emoji: 'warning', enabled: false },
        polite: { emoji: 'orange_heart', enabled: true },
    },
    default_integration_id: null,
    project_options: [
        { integration_id: 7, project_name: 'Hedgebox web', organization_name: 'Hedgebox' },
        { integration_id: 8, project_name: 'Hedgebox mobile', organization_name: 'Hedgebox' },
    ],
    untagged_followup_mode: 'ask',
    untagged_question_mode: 'ask',
    thread_join_mode: 'allow',
    auto_model_choice: false,
    feature_tips_enabled: true,
}

function settingsDecorator(personal: Record<string, unknown>): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/environments/:team_id/integrations/': INTEGRATIONS,
            '/api/projects/:team_id/integrations/': INTEGRATIONS,
            '/api/projects/:team_id/slack_app_settings/:id/': {
                integration_id: 7,
                slack_workspace_name: 'Hedgebox',
                can_edit_workspace: true,
                workspace: { reactions: REACTIONS, external_channels_enabled: false },
                personal,
            },
        },
    })
}

const meta: Meta<typeof SlackAppPersonalSettings> = {
    title: 'Scenes-App/Slack app/Personal settings',
    component: SlackAppPersonalSettings,
    parameters: { mockDate: '2023-01-01', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof SlackAppPersonalSettings>

export const Linked: Story = {
    decorators: [settingsDecorator(PERSONAL)],
}

export const NotLinked: Story = {
    decorators: [settingsDecorator({ ...PERSONAL, slack_user_id: null })],
}
