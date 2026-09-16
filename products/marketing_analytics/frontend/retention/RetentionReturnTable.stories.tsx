import type { Meta, StoryObj } from '@storybook/react'

import { RetentionReturnTable } from './RetentionReturnTable'

const meta: Meta<typeof RetentionReturnTable> = {
    title: 'Marketing analytics/Retention return table',
    component: RetentionReturnTable,
    args: {
        dimensionLabel: 'Source',
        loading: false,
        compare: true,
        rows: [
            {
                breakdownValue: 'newsletter',
                previous: false,
                acquired: 400,
                eligible7d: 320,
                returned7d: 80,
                eligible30d: 200,
                returned30d: 70,
                returners: 130,
                medianReturnDays: 3.5,
            },
            {
                breakdownValue: 'newsletter',
                previous: true,
                acquired: 350,
                eligible7d: 350,
                returned7d: 70,
                eligible30d: 350,
                returned30d: 105,
                returners: 105,
                medianReturnDays: 4.8,
            },
            {
                breakdownValue: 'search',
                previous: false,
                acquired: 600,
                eligible7d: 480,
                returned7d: 48,
                eligible30d: 300,
                returned30d: 60,
                returners: 95,
                medianReturnDays: 8.2,
            },
            {
                breakdownValue: 'recent-source',
                previous: false,
                acquired: 20,
                eligible7d: 0,
                returned7d: 0,
                eligible30d: 0,
                returned30d: 0,
                returners: 0,
                medianReturnDays: null,
            },
        ],
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const Default: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}
export const Loading: Story = { args: { loading: true, rows: [] } }
export const Empty: Story = { args: { rows: [] } }
