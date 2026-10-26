import { Meta, StoryObj } from '@storybook/react'

import { EnableWorkflowPrompt } from './EnableWorkflowPrompt'

const meta: Meta<typeof EnableWorkflowPrompt> = {
    title: 'Products/Workflows/Enable workflow prompt',
    component: EnableWorkflowPrompt,
    args: {
        onConfirm: () => {},
        onCancel: () => {},
    },
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForSelector: '[data-attr="workflow-enable-prompt-confirm"]' },
    },
}
export default meta

type Story = StoryObj<typeof EnableWorkflowPrompt>

export const OneUnverifiedDomain: Story = { args: { domains: ['example.com'] } }

export const SeveralUnverifiedDomains: Story = { args: { domains: ['example.com', 'mail.example.org'] } }
