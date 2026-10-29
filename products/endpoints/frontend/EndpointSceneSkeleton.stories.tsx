import { Meta, StoryObj } from '@storybook/react'

import { EndpointSceneSkeleton } from './EndpointSceneSkeleton'

const meta: Meta<typeof EndpointSceneSkeleton> = {
    title: 'Endpoints/Endpoint scene skeleton',
    component: EndpointSceneSkeleton,
    parameters: {
        testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof EndpointSceneSkeleton>

export const Default: Story = {}

export const WithoutTabs: Story = { args: { showTabs: false } }

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-120">
                <Story />
            </div>
        ),
    ],
}
