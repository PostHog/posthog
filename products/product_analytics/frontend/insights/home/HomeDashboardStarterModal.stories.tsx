import { Meta, StoryObj } from '@storybook/react'

import { HomeDashboardStarterModal } from './HomeDashboardStarterModal'

const noop = (): void => undefined

const meta: Meta<typeof HomeDashboardStarterModal> = {
    component: HomeDashboardStarterModal,
    title: 'Scenes-App/Product analytics home dashboard starter',
    args: {
        isOpen: true,
        onClose: noop,
        onTalkToAI: noop,
        onStartFromTemplate: noop,
        onChooseExisting: noop,
        onRestorePostHogHome: noop,
        hasCustomDashboard: false,
    },
    parameters: {
        layout: 'fullscreen',
    },
}
export default meta

type Story = StoryObj<typeof HomeDashboardStarterModal>

export const Default: Story = {}

export const WithCustomDashboard: Story = {
    args: { hasCustomDashboard: true },
}

export const CreatingWithAI: Story = {
    args: { hasCustomDashboard: true, creatingWithAI: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const AIUnavailable: Story = {
    args: { aiDisabledReason: 'Approve AI data processing to use PostHog AI' },
}

export const Narrow: Story = {
    args: { hasCustomDashboard: true },
    parameters: { testOptions: { viewport: { width: 552, height: 900 } } },
}
