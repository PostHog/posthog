import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { SlackAppPersonalSettings } from './SlackAppPersonalSettings'
import { SlackAppWorkspaceSettings } from './SlackAppWorkspaceSettings'

const INTEGRATIONS = {
    results: [{ id: 7, kind: 'slack', display_name: 'Hedgebox', config: {}, created_at: '2023-01-01T00:00:00Z' }],
}

// An inline image, so the story loads no file from outside Storybook.
const HOG_EMOJI =
    'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="%23f9bd2b"/></svg>'

const EFFECTIVE = {
    working: { emoji: 'hog-thinking', enabled: true },
    done: { emoji: 'white_check_mark', enabled: false },
    error: { emoji: 'x', enabled: true },
    polite: { emoji: 'orange_heart', enabled: true },
}

const WORKSPACE_REACTIONS = {
    working: { emoji: 'hog-thinking', enabled: null },
    done: { emoji: null, enabled: null },
    error: { emoji: null, enabled: null },
    polite: { emoji: null, enabled: null },
}

const PERSONAL_REACTIONS = {
    working: { emoji: null, enabled: null },
    done: { emoji: 'tada', enabled: true },
    error: { emoji: null, enabled: null },
    polite: { emoji: null, enabled: false },
}

function settingsDecorator({
    canEditWorkspace,
    customEmojiStatus,
}: {
    canEditWorkspace: boolean
    customEmojiStatus: 'loaded' | 'missing_scope'
}): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/environments/:team_id/integrations/': INTEGRATIONS,
            '/api/projects/:team_id/integrations/': INTEGRATIONS,
            '/api/projects/:team_id/slack_app_settings/:id/': {
                integration_id: 7,
                slack_workspace_name: 'Hedgebox',
                can_edit_workspace: canEditWorkspace,
                workspace: {
                    reactions: WORKSPACE_REACTIONS,
                    effective_reactions: EFFECTIVE,
                    external_channels_enabled: false,
                },
                personal: {
                    slack_user_id: 'U123',
                    reactions: PERSONAL_REACTIONS,
                    effective_reactions: {
                        ...EFFECTIVE,
                        done: { emoji: 'tada', enabled: true },
                        polite: { emoji: 'orange_heart', enabled: false },
                    },
                    default_integration_id: null,
                    project_options: [],
                    untagged_followup_mode: 'ask',
                    untagged_question_mode: 'ask',
                    thread_join_mode: 'allow',
                    auto_model_choice: false,
                    feature_tips_enabled: true,
                    chatgpt_apps_enabled: null,
                },
            },
            '/api/projects/:team_id/slack_app_settings/:id/channels/': { channels: [] },
            '/api/projects/:team_id/slack_app_settings/:id/emoji/': {
                custom_emoji:
                    customEmojiStatus === 'loaded'
                        ? [{ name: 'hog-thinking', image_url: HOG_EMOJI, alias_for: null }]
                        : [],
                custom_emoji_status: customEmojiStatus,
            },
        },
    })
}

const meta: Meta = {
    title: 'Scenes-App/Slack app/Reaction settings',
    parameters: {
        mockDate: '2023-01-01',
        featureFlags: [FEATURE_FLAGS.SLACK_APP_EMOJIS_SETTINGS],
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj

export const WorkspaceWithCustomEmoji: Story = {
    render: () => <SlackAppWorkspaceSettings />,
    decorators: [settingsDecorator({ canEditWorkspace: true, customEmojiStatus: 'loaded' })],
}

export const PersonalWithoutCustomEmojiScope: Story = {
    render: () => <SlackAppPersonalSettings />,
    decorators: [settingsDecorator({ canEditWorkspace: false, customEmojiStatus: 'missing_scope' })],
}
