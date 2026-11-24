import { Meta, StoryObj } from '@storybook/react'

import { ImportWizardStepper } from './ImportWizardStepper'
import { QuillImportWizardStepper } from './QuillImportWizardStepper'

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

const STEPS = [
    { key: 'source', label: 'Tool' },
    { key: 'location', label: 'URL' },
    { key: 'token', label: 'Token' },
    { key: 'import', label: 'Import' },
]

/** Two finished steps, the current step, and one step that is not reachable yet. */
export const ThirdStep: Story = {
    render: () => <ImportWizardStepper steps={STEPS} currentStep="token" onStepClick={() => {}} />,
}

/** The same steps in the quill version, which shows behind the new navigation. */
export const QuillThirdStep: Story = {
    parameters: { testOptions: { snapshotBrowsers: [] } },
    render: () => (
        <div data-quill>
            <QuillImportWizardStepper steps={STEPS} currentStep="token" onStepClick={() => {}} />
        </div>
    ),
}
