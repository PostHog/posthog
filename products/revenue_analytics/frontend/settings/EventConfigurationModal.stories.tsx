import { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { EventConfigurationModal, EventConfigurationModalProps } from './EventConfigurationModal'

const meta: Meta<EventConfigurationModalProps> = {
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

type Story = StoryObj<EventConfigurationModalProps>
export const Default: Story = {
    args: { onClose: () => {} },
}
