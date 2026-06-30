import type { Meta, StoryObj } from '@storybook/react'

import { Welcome } from './Welcome'
import { DEFAULT_HEADLINES } from './welcomeDefaults'

const meta: Meta<typeof Welcome> = {
    title: 'Products/PostHog AI/Welcome',
    component: Welcome,
    tags: ['autodocs'],
    args: { headline: DEFAULT_HEADLINES[1] },
    render: (args) => (
        <div className="flex flex-col items-center max-w-2xl mx-auto p-4">
            <Welcome {...args} />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof Welcome>

/** Default — logomark, headline, and the PostHog AI tagline. */
export const Default: Story = {}

/** A caller-supplied subheadline replaces the default tagline. */
export const CustomSubheadline: Story = {
    args: { subheadline: 'Ship faster with PostHog AI.' },
}

/** Passing `null` hides the subheadline entirely. */
export const NoSubheadline: Story = {
    args: { subheadline: null },
}
