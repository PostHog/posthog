import { Meta, StoryObj } from '@storybook/react'
import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS],
        pageUrl: urls.revenueSettings(),
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const RevenueAnalyticsSettings: Story = {}
