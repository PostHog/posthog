import type { Meta, StoryObj } from '@storybook/react'

import { weeklyDigestBundle } from '@posthog/agent-chat/fixtures'

import { BundleTree } from './BundleTree'

const meta: Meta<typeof BundleTree> = {
    title: 'Agent console components/BundleTree',
    component: BundleTree,
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <div className="h-screen p-6">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof BundleTree>

export const Default: Story = {
    args: {
        files: weeklyDigestBundle,
    },
}

export const FocusedOnSkill: Story = {
    args: {
        files: weeklyDigestBundle,
        initialPath: 'skills/pr-callouts.md',
    },
}

export const FocusedOnToolSchema: Story = {
    args: {
        files: weeklyDigestBundle,
        initialPath: 'tools/in-app-helper/schema.json',
    },
}

export const Empty: Story = {
    args: {
        files: [],
    },
}
