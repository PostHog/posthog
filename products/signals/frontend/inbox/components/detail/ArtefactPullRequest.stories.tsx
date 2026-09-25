import type { Meta, StoryObj } from '@storybook/react'

import { LemonCard } from '@posthog/lemon-ui'

import { ArtefactPullRequest } from './ArtefactPullRequest'

const meta: Meta<typeof ArtefactPullRequest> = {
    title: 'Scenes-App/Signals/ArtefactPullRequest',
    component: ArtefactPullRequest,
    decorators: [
        (Story) => (
            <LemonCard className="max-w-sm">
                <Story />
            </LemonCard>
        ),
    ],
    args: {
        url: 'https://github.com/exampleorg/exampleplatformservice/pull/48261',
        implementationTitle: 'Handle retries at the request boundary and preserve the original response',
        state: 'open',
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const Open: Story = {}
export const Unavailable: Story = { args: { implementationTitle: undefined, state: 'unknown' } }
export const Retained: Story = { args: { outcome: 'skipped' } }
