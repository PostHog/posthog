import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { EventConfigurationModal } from './EventConfigurationModal'

const meta: Meta = {
    component: EventConfigurationModal,
    title: 'Scenes-App/Data Management/Revenue Analytics/Event Configuration Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS, FEATURE_FLAGS.MRR_BREAKDOWN_REVENUE_ANALYTICS],
        pageUrl: urls.revenueAnalytics(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const Default: Story = {}
