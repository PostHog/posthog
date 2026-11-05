import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { SourceSetupPanel } from '../dashboard/SourceSetupPanel'
import { DashboardSetupPrompt } from './DashboardSetupPrompt'

const meta: Meta<typeof DashboardSetupPrompt> = {
    title: 'Scenes-App/Marketing Analytics/Dismissible setup prompts',
    component: DashboardSetupPrompt,
    parameters: { layout: 'padded', featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP] },
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
    args: { kind: 'sources' },
}
export default meta
type Story = StoryObj<typeof DashboardSetupPrompt>

export const Scanning: Story = {
    args: {
        dismissible: false,
        children: (dismissButton) => <SourceSetupPanel state="scanning" headerAction={dismissButton} />,
    },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Failed: Story = {
    args: {
        dismissible: false,
        children: (dismissButton) => <SourceSetupPanel state="error" onRetry={() => {}} headerAction={dismissButton} />,
    },
}

export const Suggestions: Story = {
    args: { children: (dismissButton) => <SourceSetupPanel state="empty" headerAction={dismissButton} /> },
}
export const WithoutSetup: Story = {
    ...Suggestions,
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]: false,
        },
    },
}
