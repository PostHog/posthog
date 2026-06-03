import type { Meta, StoryFn, StoryObj } from '@storybook/react'

import { StatStrip } from './StatStrip'

const meta: Meta<typeof StatStrip> = {
    title: 'Agent console components/StatStrip',
    component: StatStrip,
    parameters: { layout: 'centered' },
    decorators: [
        (Story: StoryFn) => (
            <div className="w-[860px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof StatStrip>

export const Fleet: Story = {
    args: {
        tiles: [
            { label: 'Agents', value: 4, hint: 'in this project' },
            { label: 'Live now', value: 4, hint: 'sessions in flight' },
            { label: 'Sessions · 24h', value: '87', hint: 'across all agents' },
            { label: 'Spend · 24h', value: '$12.43', hint: '1 approval pending', tone: 'attention' },
        ],
    },
}

export const PerAgent: Story = {
    args: {
        tiles: [
            { label: 'Sessions · 24h', value: '14' },
            { label: 'Avg cost', value: '$0.041' },
            { label: 'Tool calls · 24h', value: '187' },
            { label: 'p95 latency', value: '4.2s' },
        ],
    },
}

export const ZeroState: Story = {
    args: {
        tiles: [
            { label: 'Agents', value: 0, hint: 'create your first' },
            { label: 'Live now', value: 0 },
            { label: 'Sessions · 24h', value: 0 },
            { label: 'Spend · 24h', value: '$0.00' },
        ],
    },
}
