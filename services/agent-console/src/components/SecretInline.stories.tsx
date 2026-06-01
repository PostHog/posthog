import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { SecretInline } from './SecretInline'

const meta: Meta<typeof SecretInline> = {
    title: 'Agent console components/SecretInline',
    component: SecretInline,
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            <div className="w-[420px] rounded-md border border-border bg-card p-3">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof SecretInline>

const noop = (): void => undefined

/**
 * The form as the agent first renders it — no value entered, save
 * disabled. Mirrors the in-chat appearance when the concierge invokes
 * `set_secret({ secret: 'ANTHROPIC_KEY' })`.
 */
export const Idle: Story = {
    args: {
        agentSlug: 'weekly-digest',
        secret: 'ANTHROPIC_KEY',
        mode: 'set',
        purpose: 'Needed by the agent to call Anthropic for one-off summaries.',
        onSetSecret: async () => {
            await new Promise((r) => setTimeout(r, 300))
        },
        onResolve: (body) => console.info('[mock] resolve', body),
        onReject: (reason) => console.info('[mock] reject', reason),
    },
}

/**
 * The rotate variant — copy + button label switch to "Rotate". Use this
 * when `agent-applications-env-keys-get` returns `is_set: true` and the
 * agent is replacing the value rather than creating it.
 */
export const Rotate: Story = {
    args: {
        ...Idle.args,
        secret: 'STRIPE_SECRET_KEY',
        mode: 'rotate',
        purpose: 'The current value was rejected as expired — paste the new one from your Stripe dashboard.',
    },
}

/**
 * After a successful save the form collapses to a single success
 * confirmation. The matching tool-call card in the chat would also
 * flip its status dot to green once the runner's `tool_result` event
 * reflows in.
 */
export const Saved: Story = {
    render: (args) => {
        // Start with a setter that resolves instantly so the success
        // state is what's on screen as soon as the story mounts.
        const [submitted, setSubmitted] = useState(false)
        return (
            <SecretInline
                {...args}
                onSetSecret={async () => {
                    setSubmitted(true)
                }}
                onResolve={(body) => console.info('[mock] resolve', body, submitted)}
                onReject={noop}
            />
        )
    },
    args: {
        agentSlug: 'weekly-digest',
        secret: 'ANTHROPIC_KEY',
        mode: 'set',
        onSetSecret: async () => undefined,
        onResolve: noop,
        onReject: noop,
    },
    play: async ({ canvasElement }) => {
        // Drive the form to the saved state so the screenshot matches.
        const root = canvasElement
        const input = root.querySelector('input[type="password"]') as HTMLInputElement | null
        const button = root.querySelector('button[type="submit"]') as HTMLButtonElement | null
        if (input && button) {
            input.value = 'sk-...'
            input.dispatchEvent(new Event('input', { bubbles: true }))
            button.click()
        }
    },
}

/**
 * The setter fails — surface the error inline and let the user retry
 * without dismissing the form. The agent stays blocked until the user
 * either retries successfully or cancels.
 */
export const ApiError: Story = {
    args: {
        ...Idle.args,
        onSetSecret: async () => {
            await new Promise((r) => setTimeout(r, 200))
            throw new Error('400 Bad Request: value too short')
        },
    },
    play: async ({ canvasElement }) => {
        const root = canvasElement
        const input = root.querySelector('input[type="password"]') as HTMLInputElement | null
        const button = root.querySelector('button[type="submit"]') as HTMLButtonElement | null
        if (input && button) {
            input.value = 'x'
            input.dispatchEvent(new Event('input', { bubbles: true }))
            button.click()
        }
    },
}
