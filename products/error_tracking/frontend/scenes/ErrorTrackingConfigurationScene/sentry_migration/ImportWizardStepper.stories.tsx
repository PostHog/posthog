import { Meta, StoryObj } from '@storybook/react'

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
    ),
}
