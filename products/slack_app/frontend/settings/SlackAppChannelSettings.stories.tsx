import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { SlackAppChannelSettings } from './SlackAppChannelSettings'

const INTEGRATIONS = {
    results: [{ id: 7, kind: 'slack', display_name: 'Hedgebox', config: {}, created_at: '2023-01-01T00:00:00Z' }],
}

const REACTION = { emoji: null, enabled: null }
const REACTIONS = { working: REACTION, done: REACTION, error: REACTION, polite: REACTION }

const SETTINGS = {
    integration_id: 7,
    slack_workspace_name: 'Hedgebox',
    can_edit_workspace: false,
    workspace: { reactions: REACTIONS, external_channels_enabled: false },
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
        project_options: [
            { integration_id: 7, project_name: 'Hedgebox web', organization_name: 'Hedgebox' },
            { integration_id: 8, project_name: 'Hedgebox mobile', organization_name: 'Hedgebox' },
        ],
        untagged_followup_mode: 'ask',
        untagged_question_mode: 'ask',
        thread_join_mode: 'allow',
        auto_model_choice: false,
        feature_tips_enabled: true,
    },
}

function channelsDecorator(channels: Record<string, unknown>[]): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/environments/:team_id/integrations/': INTEGRATIONS,
            '/api/projects/:team_id/integrations/': INTEGRATIONS,
            '/api/projects/:team_id/slack_app_settings/:id/': SETTINGS,
            '/api/projects/:team_id/slack_app_settings/:id/channels/': { channels },
            '/api/projects/:team_id/slack_app_settings/:id/repositories/': {
                repositories: ['hedgebox/api', 'hedgebox/mobile', 'hedgebox/web'],
                github_connected: true,
            },
            '/api/environments/:team_id/integrations/:id/channels': {
                channels: [
                    { id: 'C1', name: 'support', is_private: false, is_ext_shared: false, is_member: true },
                    { id: 'C2', name: 'team-mobile', is_private: true, is_ext_shared: false, is_member: true },
                    { id: 'C3', name: 'random', is_private: false, is_ext_shared: false, is_member: true },
                    { id: 'C4', name: 'partner-acme', is_private: false, is_ext_shared: true, is_member: true },
                ],
                lastRefreshedAt: '2023-01-10T00:00:00Z',
            },
        },
    })
}

const meta: Meta<typeof SlackAppChannelSettings> = {
    title: 'Scenes-App/Slack app/Channel settings',
    component: SlackAppChannelSettings,
    parameters: { mockDate: '2023-01-10', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof SlackAppChannelSettings>

export const WithChannels: Story = {
    decorators: [
        channelsDecorator([
            {
                slack_channel_id: 'C1',
                default_integration_id: 7,
                default_repository: 'hedgebox/web',
                untagged_question_mode: 'ask',
                updated_by_name: 'Jamie',
                updated_at: '2023-01-08T10:00:00Z',
            },
            {
                slack_channel_id: 'C2',
                default_integration_id: 8,
                default_repository: 'hedgebox/mobile',
                untagged_question_mode: null,
                updated_by_name: 'Alex',
                updated_at: '2023-01-09T10:00:00Z',
            },
            {
                slack_channel_id: 'C3',
                default_integration_id: null,
                default_repository: null,
                untagged_question_mode: 'never',
                updated_by_name: 'Sam',
                updated_at: '2022-12-20T10:00:00Z',
            },
        ]),
    ],
}

export const Empty: Story = {
    decorators: [channelsDecorator([])],
}
