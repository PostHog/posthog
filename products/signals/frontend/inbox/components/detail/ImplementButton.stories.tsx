import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'

import { makeReport } from '../../__mocks__/inboxMocks'
import { reportGithubAccessLogic } from '../../logics/reportGithubAccessLogic'
import { ImplementButton } from './ImplementButton'

const meta: Meta<typeof ImplementButton> = {
    title: 'Scenes-App/Inbox/ImplementButton',
    component: ImplementButton,
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof ImplementButton>

const report = makeReport({ title: 'Exceptions spiked after the 18 June deploy' })

export const Default: Story = {
    render: () => <ImplementButton report={report} />,
}

export const Choices: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.Popover' } },
    render: () => <ImplementButton report={report} />,
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('More implementation options'))
        await waitFor(() => {
            if (!document.querySelector('.Popover')) {
                throw new Error('implementation choices not open yet')
            }
        })
    },
}

export const ConnectGithub: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.LemonModal' } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': {
                    draft: null,
                    completed_at: null,
                    github_optional_available: true,
                },
                '/api/projects/:id/integrations/': { results: [], next: null },
                '/api/projects/:id/integrations/github/available_installations/': {
                    installations: [],
                    personal_github_connected: false,
                },
            },
        }),
    ],
    render: () => <ImplementButton report={report} />,
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Implement'))
        const implement = await waitFor(() => {
            if (!reportGithubAccessLogic({ report }).values.repairNeeded) {
                throw new Error('GitHub connection requirement has not resolved')
            }
            const button = within(document.body).getByText('Implement with PostHog').closest('button')!
            if (button.getAttribute('aria-disabled') === 'true') {
                throw new Error('GitHub check has not finished')
            }
            return button
        })
        await userEvent.click(implement)
        await within(document.body).findByText('Connect GitHub account')
    },
}
