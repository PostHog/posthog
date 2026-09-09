import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { SlackNotificationsSection } from './SlackNotificationsSection'

const WORKSPACE = { id: 1, kind: 'slack', display_name: 'PostHog', config: {}, created_at: '2026-01-01T00:00:00Z' }

const CHANNELS = [
    { id: 'C0123ABC456', name: 'self-driving', is_private: false, is_member: true, is_ext_shared: false },
    { id: 'C0456DEF789', name: 'engineering', is_private: false, is_member: true, is_ext_shared: false },
]

interface CardsState {
    connected?: boolean
    teamChannel?: string | null
    /** The personal reviewer ping target: the person's own account (`U…|@name`) or a channel. */
    myTarget?: string | null
    /** Personal notifications turned on with no target chosen yet. */
    awaitingTarget?: boolean
}

function Cards({
    connected = true,
    teamChannel = null,
    myTarget = null,
    awaitingTarget = false,
}: CardsState): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/integrations/': { results: connected ? [WORKSPACE] : [] },
            '/api/environments/:team_id/integrations/:id/channels': { channels: CHANNELS, has_more: false },
            '/api/projects/:team_id/signals/config/': {
                id: 'cfg-1',
                default_slack_notification_channel: teamChannel,
                default_autostart_priority: 'P2',
                autostart_base_branches: {},
            },
            '/api/users/@me/signal_autonomy/': {
                id: 'auto-1',
                autostart_priority: null,
                slack_notification_integration_id: myTarget || awaitingTarget ? WORKSPACE.id : null,
                slack_notification_channel: myTarget,
                slack_notification_min_priority: null,
            },
        },
    })
    // Mimic the agents rail (`w-80` aside + the column's `px-4 py-3`) so the cards lay out as in the scene.
    return (
        <div className="w-80 px-4 py-3 bg-surface-secondary">
            <SlackNotificationsSection />
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/SlackNotificationsSection',
    component: SlackNotificationsSection,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2024-03-20',
    },
}
export default meta

type Story = StoryObj

export const NotConnected: Story = {
    render: () => <Cards connected={false} />,
}

export const NothingConfigured: Story = {
    render: () => <Cards />,
}

export const AwaitingTarget: Story = {
    render: () => <Cards awaitingTarget />,
}

export const DirectMessageToMe: Story = {
    render: () => <Cards myTarget="U0123ABC456|@sam" />,
}

export const PersonalChannel: Story = {
    render: () => <Cards teamChannel="C0456DEF789|#engineering" myTarget="C0123ABC456|#self-driving" />,
}
