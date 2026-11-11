import type { Meta, StoryObj } from '@storybook/react'

import { WizardRailButtonView } from './WizardRailButtonView'

const meta: Meta<typeof WizardRailButtonView> = {
    title: 'Products/Wizard/Wizard rail button',
    component: WizardRailButtonView,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false },
    },
    decorators: [
        (Story) => (
            <div className="flex w-[60px] justify-center bg-[var(--chrome)] py-3">
                <Story />
            </div>
        ),
    ],
    args: {
        state: 'idle',
        progress: 0,
        open: false,
        onOpenChange: () => {},
        panel: <div className="w-80 p-3 text-sm">Wizard runs</div>,
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const Idle: Story = {}

export const Running: Story = { args: { state: 'running', progress: 0.55 } }

export const Completed: Story = { args: { state: 'completed' } }

export const Failed: Story = { args: { state: 'failed' } }
