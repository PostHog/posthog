import { Meta, StoryObj } from '@storybook/react'

import { MarketingQueryError } from './MarketingQueryError'

const meta: Meta<typeof MarketingQueryError> = {
    title: 'Marketing Analytics/Query error',
    component: MarketingQueryError,
    args: {
        message: 'Could not load traffic metrics. Try again.',
        queryId: '00000000-0000-4000-8000-000000000001',
        onRetry: () => {},
    },
    render: (args) => (
        // A 960 px scene prevents component snapshots from collapsing the banner's container query.
        <div className="w-[60rem] max-w-full">
            <MarketingQueryError {...args} />
        </div>
    ),
}
export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const WithoutQueryId: Story = { args: { queryId: null } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[32.5rem] max-w-full">
                {/* A 520 px scene models the space beside an open side panel. */}
                <Story />
            </div>
        ),
    ],
}
