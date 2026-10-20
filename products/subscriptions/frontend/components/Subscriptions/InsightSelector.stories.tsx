import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { DashboardTile } from '~/types'

import { InsightSelector } from './InsightSelector'

const tiles = [
    { id: 1, insight: { id: 101, name: 'Pageviews' }, layouts: { sm: { x: 0, y: 0 } } },
    { id: 2, insight: { id: 102, name: 'Sessions' }, layouts: { sm: { x: 0, y: 1 } } },
] as DashboardTile[]

const meta: Meta<typeof InsightSelector> = {
    title: 'Subscriptions/InsightSelector',
    component: InsightSelector,
    parameters: { layout: 'padded' },
    args: { tiles },
    render: function Render(args): JSX.Element {
        const [selectedIds, setSelectedIds] = useState(args.selectedInsightIds)
        return <InsightSelector {...args} selectedInsightIds={selectedIds} onChange={setSelectedIds} />
    },
}
export default meta

type Story = StoryObj<typeof InsightSelector>

export const SomeUnavailable: Story = { args: { selectedInsightIds: [101, 998] } }
export const AllUnavailable: Story = { args: { selectedInsightIds: [998, 999] } }
export const EmptyDashboard: Story = { args: { tiles: [], selectedInsightIds: [999] } }
