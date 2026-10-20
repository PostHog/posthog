import { Meta, StoryObj } from '@storybook/react'

import { WorkflowSenderDomainNotice } from './WorkflowSenderDomainNotice'

const meta: Meta<typeof WorkflowSenderDomainNotice> = {
    title: 'Products/Workflows/Sender domain notice',
    component: WorkflowSenderDomainNotice,
    parameters: {
        testOptions: { waitForSelector: '[data-attr^="workflow-sender-domain"]' },
    },
}
export default meta

type Story = StoryObj<typeof WorkflowSenderDomainNotice>

export const NoDomain: Story = { args: { notice: { stage: 'no_domain', url: '/workflows/channels' } } }

export const UnverifiedDomain: Story = {
    args: { notice: { stage: 'unverified', domains: ['mail.example.com'], url: '/workflows/channels' } },
}

export const WaitingForSeveralDomains: Story = {
    args: {
        notice: { stage: 'waiting', domains: ['mail.example.com', 'news.example.org'], url: '/workflows/channels' },
    },
}
