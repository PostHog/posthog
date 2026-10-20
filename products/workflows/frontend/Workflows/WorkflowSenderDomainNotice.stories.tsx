import { Meta, StoryObj } from '@storybook/react'

import { WorkflowSenderDomainNotice } from './WorkflowSenderDomainNotice'

const meta: Meta<typeof WorkflowSenderDomainNotice> = {
    title: 'Products/Workflows/Sender domain notice',
    component: WorkflowSenderDomainNotice,
    args: { onOpenDomainSetup: () => {} },
    parameters: {
        testOptions: { waitForSelector: '[data-attr^="workflow-sender-domain"]' },
    },
}
export default meta

type Story = StoryObj<typeof WorkflowSenderDomainNotice>

export const NoDomain: Story = { args: { notice: { stage: 'no_domain' } } }

export const UnverifiedDomain: Story = {
    args: { notice: { stage: 'unverified', domains: ['mail.example.com'], integrationId: 1 } },
}

export const WaitingForSeveralDomains: Story = {
    args: { notice: { stage: 'waiting', domains: ['mail.example.com', 'news.example.org'], integrationId: null } },
}
