import { Meta, StoryObj } from '@storybook/react'

import { HomeTabEmptyDashboard } from './HomeTabEmptyDashboard'

const noop = (): void => undefined

const meta: Meta<typeof HomeTabEmptyDashboard> = {
    component: HomeTabEmptyDashboard,
    title: 'Scenes-App/Product analytics home empty dashboard',
    args: {
        onContinueWithAI: noop,
        onResetToDefault: noop,
    },
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof HomeTabEmptyDashboard>

export const Default: Story = {}

export const AIUnavailable: Story = {
    args: { aiDisabledReason: 'Approve AI data processing to use PostHog AI' },
}
