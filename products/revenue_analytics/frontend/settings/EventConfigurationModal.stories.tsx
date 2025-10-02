import { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { EventConfigurationModal } from './EventConfigurationModal'

const meta: Meta = {
    component: EventConfigurationModal,
    title: 'Scenes-App/Data Management/Revenue Analytics/Event Configuration Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.revenueAnalytics(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const Default: Story = {
    args: { onClose: () => {} },
}
