import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { ScoutMcpServersPicker } from './ScoutMcpServersPicker'

/** Stories drive the picker like its call sites do: selection state lives outside. */
function ControlledPicker({ compact }: { compact?: boolean }): JSX.Element {
    const [selectedServerIds, setSelectedServerIds] = useState<string[]>(['linear-id'])
    return (
        <ScoutMcpServersPicker
            compact={compact}
            selectedServerIds={selectedServerIds}
            onChange={setSelectedServerIds}
        />
    )
}

const YOU = { id: 179, uuid: 'you-uuid', email: 'you@posthog.com', hedgehog_config: null }
const TEAMMATE = { id: 2, uuid: 'mate-uuid', email: 'mate@posthog.com', hedgehog_config: null }

function grant(
    id: string,
    name: string,
    sharedBy = YOU,
    scope = 'team',
    connectionState = 'ready'
): Record<string, unknown> {
    return {
        id,
        shared_by: sharedBy,
        scope,
        name,
        description: `${name} workspace`,
        icon_key: name.toLowerCase(),
        icon_domain: `${name.toLowerCase()}.com`,
        connection_state: connectionState,
    }
}

const scoutAccount = {
    id: 'scout-account-id',
    name: 'Scout',
    description: 'Scheduled scouts',
    handle: 'svc-scout',
    agent_key: 'scout',
    status: 'active',
    server_ids: ['linear-id', 'notion-id', 'github-id', 'stripe-id', 'slack-id'],
    servers: [
        grant('linear-id', 'Linear'),
        grant('notion-id', 'Notion', TEAMMATE),
        grant('github-id', 'GitHub', TEAMMATE),
        grant('stripe-id', 'Stripe', YOU, 'team', 'needs_reauth'),
        grant('slack-id', 'Slack'),
        // Personal grants never back a scout run, so this one must not render.
        grant('zendesk-id', 'Zendesk', YOU, 'personal'),
    ],
    last_active_at: null,
    created_at: '2026-07-22T00:00:00Z',
    updated_at: '2026-07-22T00:00:00Z',
}

const meta: Meta<typeof ScoutMcpServersPicker> = {
    title: 'Scenes-App/Inbox/ScoutMcpServersPicker',
    component: ScoutMcpServersPicker,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/mcp_gateway/service_accounts/': () => [
                    200,
                    { count: 1, next: null, previous: null, results: [scoutAccount] },
                ],
            },
        }),
    ],
    parameters: {
        testOptions: { waitForLoadersToDisappear: true },
        featureFlags: [FEATURE_FLAGS.MCP_GATEWAY],
    },
}
export default meta
type Story = StoryObj<typeof ScoutMcpServersPicker>

export const CreateDialogVariant: Story = {
    render: () => (
        <div className="max-w-2xl p-4">
            <ControlledPicker />
        </div>
    ),
}

export const ScoutSettingsVariant: Story = {
    render: () => (
        <div className="max-w-md p-4">
            <ControlledPicker compact />
        </div>
    ),
}
