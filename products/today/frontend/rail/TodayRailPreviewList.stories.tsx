import { Meta, StoryObj } from '@storybook/react'

import { IconGraph, IconNotebook } from '@posthog/icons'
import { Card } from '@posthog/quill'

import { TodayRailPreviewList } from './TodayRailPreviewList'

const meta: Meta<typeof TodayRailPreviewList> = {
    title: 'Layout/Today/Rail preview',
    component: TodayRailPreviewList,
    decorators: [
        (Story) => (
            <Card size="sm" className="w-72 gap-0 py-0 empty:hidden">
                <Story />
            </Card>
        ),
    ],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        pane: 'analytics',
        title: 'Analytics',
        pins: [{ name: 'Activation funnel', href: '/insights/activation', icon: <IconGraph /> }],
        recents: [{ name: 'Weekly notes', href: '/notebooks/weekly', icon: <IconNotebook /> }],
        onAction: () => {},
    },
}
export default meta

type Story = StoryObj<typeof TodayRailPreviewList>

export const PinnedAndRecent: Story = {}

export const LongList: Story = {
    args: {
        pins: Array.from({ length: 12 }, (_, i) => ({
            name: `Dashboard ${i + 1}`,
            href: `/dashboard/${i + 1}`,
            icon: <IconGraph />,
        })),
        recents: [
            {
                name: 'A long notebook title that must stay inside the hover card without horizontal scrolling',
                href: '/notebooks/long-title',
                icon: <IconNotebook />,
            },
            { name: 'Weekly notes', href: '/notebooks/weekly', icon: <IconNotebook /> },
            { name: 'Retention by plan', href: '/insights/retention', icon: <IconGraph /> },
        ],
    },
}

export const Empty: Story = { args: { pins: [], recents: [] } }

export const Loading: Story = { args: { pins: [], recents: [], loading: true } }

export const Failed: Story = { args: { title: 'Chats', pins: [], recents: [], failed: true } }
