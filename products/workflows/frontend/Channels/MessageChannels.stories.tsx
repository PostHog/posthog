import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { MessageChannels } from './MessageChannels'

const SANDBOX_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'Acme via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', name: 'Acme via PostHog', email: 'sandbox@example.com', verified: true },
    created_at: '2026-08-18T00:00:00Z',
}

const OWN_SENDER = {
    id: 8,
    kind: 'email',
    display_name: 'Acme <hello@acme.example.com>',
    config: {
        provider: 'ses',
        name: 'Acme',
        email: 'hello@acme.example.com',
        domain: 'acme.example.com',
        verified: true,
    },
    created_at: '2026-08-18T00:00:00Z',
}

type StoryArgs = { integrations: Record<string, unknown>[] }

const meta: Meta<StoryArgs> = {
    title: 'Products/Workflows/Channels',
    component: MessageChannels,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER],
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ integrations }) => {
    useStorybookMocks({
        get: { '/api/projects/:team_id/integrations/': { results: integrations } },
        post: { '/api/projects/:team_id/integrations/email_sandbox_sender/': SANDBOX_SENDER },
    })
    return <MessageChannels />
}

export const SandboxSenderOnly: StoryFn<StoryArgs> = Template.bind({})
SandboxSenderOnly.args = { integrations: [SANDBOX_SENDER] }

export const SandboxAndOwnSender: StoryFn<StoryArgs> = Template.bind({})
SandboxAndOwnSender.args = { integrations: [SANDBOX_SENDER, OWN_SENDER] }
