import type { Meta, StoryObj } from '@storybook/react'

import { RunAlertActivity } from './RunAlertActivity'

// Logic-free leaf — the one card for every run stream/connection alert, driven entirely by props (no kea
// binding), so each story is just `args`. `reconnecting` renders a live Spinner and drives the thread footer;
// the failed kinds render inline in the thread for genuine agent failures.
const meta: Meta<typeof RunAlertActivity> = {
    title: 'Products/PostHog AI/RunAlertActivity',
    component: RunAlertActivity,
    tags: ['autodocs'],
    render: (args) => (
        <div className="max-w-180 mx-auto p-4">
            <RunAlertActivity {...args} />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof RunAlertActivity>

/** Terminal state after reconnect attempts are exhausted — title only, no detail to surface. */
export const ConnectionLost: Story = {
    args: { kind: 'connection_failed' },
}

/** Genuine agent failure — the detail message rides the always-visible region, not the collapsed body. */
export const AgentError: Story = {
    args: { kind: 'agent_error', message: 'The agent hit an unexpected error while running a tool.' },
}

/** The agent process died mid-run — same failed card, distinct title. */
export const AgentCrash: Story = {
    args: { kind: 'agent_crash', message: 'The agent stopped unexpectedly. Restart the run to continue.' },
}

/** Live reconnect banner with the attempt counter. */
export const Reconnecting: Story = {
    args: { kind: 'reconnecting', attempt: 2, maxAttempts: 10 },
    // The reconnecting icon is an indefinitely-spinning Spinner the VR snapshot runner would wait forever to
    // settle, so exclude this story from the snapshot run (same precedent as Composer's Loading story).
    tags: ['test-skip'],
}
