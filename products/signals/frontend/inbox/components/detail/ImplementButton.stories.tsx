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

export const NoRepository: Story = {
    parameters: { testOptions: { snapshotBrowsers: [] } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/integrations/': {
                    results: [{ id: 1, kind: 'github', display_name: 'Example' }],
                    next: null,
                },
                '/api/projects/:id/integrations/1/github_repos/': {
                    repositories: [{ id: 1, name: 'app', full_name: 'example/app', permissions: { push: true } }],
                    has_more: false,
                },
                '/api/projects/:id/tasks/@me/config/': { ai_run_preferences: {}, resolved_ai_run_defaults: null },
            },
            post: {
                '/api/projects/:id/tasks/': [
                    400,
                    {
                        type: 'validation_error',
                        code: 'report_implementation_repository_unresolved',
                        attr: 'repository',
                        detail: 'Select a repository to continue.',
                    },
                ],
            },
        }),
    ],
    render: () => <ImplementButton report={{ ...report, repo_slug: null }} />,
    play: async ({ canvasElement }) => {
        const button = await within(canvasElement).findByText('Implement')
        await waitFor(() => {
            const access = reportGithubAccessLogic({ report: { ...report, repo_slug: null } }).values
            if (access.loading || access.disabledReason || !access.repositoryIntegrationId) {
                throw new Error('GitHub access has not resolved')
            }
        })
        await userEvent.click(button)
        await within(document.body).findByText('Select a repository to implement this report')
    },
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
        await userEvent.click(await within(canvasElement).findByLabelText('More implementation options'))
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
