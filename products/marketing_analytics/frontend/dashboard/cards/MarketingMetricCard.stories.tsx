import { Meta, StoryObj } from '@storybook/react'

import { useArgs } from 'storybook/preview-api'

import { CardsPreview } from './CardsPreview'

const meta: Meta<typeof CardsPreview> = {
    title: 'Marketing Analytics/Dashboard/Metric cards',
    component: CardsPreview,
    args: { loading: false, setupSelected: false, missingSpec: false },
    render: function Render(args) {
        const [, updateArgs] = useArgs()
        return (
            <CardsPreview
                {...args}
                onLoadingChange={(loading) => updateArgs({ loading })}
                onSetupSelected={() => updateArgs({ setupSelected: true })}
            />
        )
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const Interactive: Story = {}
export const Loading: Story = {
    args: { loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const MissingSpec: Story = { args: { missingSpec: true } }
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
