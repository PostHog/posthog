import type { Meta, StoryObj } from '@storybook/react'

import { SourceSetupPanel } from '../dashboard/SourceSetupPanel'
import { DashboardSetupPrompt } from './DashboardSetupPrompt'

const meta: Meta<typeof DashboardSetupPrompt> = {
    title: 'Scenes-App/Marketing Analytics/Dismissible setup prompts',
    component: DashboardSetupPrompt,
    parameters: { layout: 'padded' },
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
    args: { children: (dismissButton) => <SourceSetupPanel state="scanning" headerAction={dismissButton} /> },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Failed: Story = {
    args: {
        children: (dismissButton) => <SourceSetupPanel state="error" onRetry={() => {}} headerAction={dismissButton} />,
    },
}
