import { Meta, StoryObj } from '@storybook/react'

import { TablePreview } from './TablePreview'

const meta: Meta<typeof TablePreview> = {
    title: 'Marketing Analytics/Dashboard/Breakdown table',
    component: TablePreview,
}
export default meta
type Story = StoryObj<typeof meta>

export const Interactive: Story = {}
export const Loading: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    args: { initialState: 'loading' },
}
export const Empty: Story = { args: { initialState: 'empty' } }
export const Error: Story = { args: { initialState: 'error' } }
export const Narrow: Story = {
    parameters: Loading.parameters,
    args: Loading.args,
    decorators: [
        (Story) => (
            <div className="w-[32.5rem] max-w-full">
                {/* A 520 px scene models the space beside an open side panel. */}
                <Story />
            </div>
        ),
    ],
}
export const NarrowComparison: Story = {
    args: { initiallyCompare: true },
    decorators: Narrow.decorators,
}
