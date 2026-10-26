import { Meta, StoryObj } from '@storybook/react'

import { TooltipProvider } from '@posthog/quill'

import { ImportWizardStepper } from './ImportWizardStepper'

const meta: Meta<typeof ImportWizardStepper> = {
    title: 'ErrorTracking/ImportWizardStepper',
    component: ImportWizardStepper,
    parameters: {
        layout: 'padded',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof ImportWizardStepper>

/** Two finished steps, the current step, and one step that is not reachable yet. */
export const ThirdStep: Story = {
    render: () => (
        <TooltipProvider>
            <div data-quill>
                <ImportWizardStepper
                    steps={[
                        { key: 'source', label: 'Tool' },
                        { key: 'location', label: 'URL' },
                        { key: 'token', label: 'Token' },
                        { key: 'import', label: 'Import' },
                    ]}
                    currentStep="token"
                    onStepClick={() => {}}
                />
            </div>
        </TooltipProvider>
    ),
}
