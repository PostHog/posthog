import { Meta, StoryObj } from '@storybook/react'

import { MetricChartPreview } from './MetricChartPreview'

const meta: Meta<typeof MetricChartPreview> = {
    title: 'Marketing Analytics/Dashboard/Metric chart',
    component: MetricChartPreview,
    args: {
        state: 'loaded',
        chartMode: 'breakdown',
        focusedBreakdownValue: null,
        format: 'number',
        queryId: '00000000-0000-4000-8000-000000000001',
    },
    render: (args) => <MetricChartPreview key={JSON.stringify(args)} {...args} />,
}
export default meta
type Story = StoryObj<typeof meta>

export const Interactive: Story = {}
export const Total: Story = { args: { chartMode: 'total' } }
export const Percentage: Story = { args: { format: 'percentage' } }
export const Loading: Story = {
    args: { state: 'loading' },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Refreshing: Story = { ...Loading, args: { state: 'refreshing' } }
export const Empty: Story = { args: { state: 'empty' } }
export const Error: Story = { args: { state: 'error' } }
export const Narrow: Story = {
    args: { focusedBreakdownValue: '' },
    decorators: [
        (Story) => (
            // A 520 px scene models the space beside an open side panel.
            <div className="w-[32.5rem] max-w-full">
                <Story />
            </div>
        ),
    ],
}
export const NarrowError: Story = { args: Error.args, decorators: Narrow.decorators }
