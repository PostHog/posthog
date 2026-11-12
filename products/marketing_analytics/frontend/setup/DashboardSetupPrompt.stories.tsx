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

export const Dismissible: Story = {
    args: { children: (dismissButton) => <SourceSetupPanel state="empty" headerAction={dismissButton} /> },
}
export const WithoutSetup: Story = {
    ...Dismissible,
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]: false,
        },
    },
}
