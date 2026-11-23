import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { BindingApi } from './generated/api.schemas'
import { ManagedInCodeBanner } from './ManagedInCodeBanner'

const GITHUB_BINDING: BindingApi = {
    id: '0b6f8f3e-0000-4000-8000-000000000001',
    stack_name: 'web-app',
    repository: 'example-org/web-app',
    kind: 'flag',
    key: 'checkout-v2',
    entity_id: '42',
    entity_url: null,
    source: { file: '.ph/flags/checkout.ts', export: 'checkoutV2' },
    status: 'bound',
    owned_fields: ['key', 'name', 'tags'],
}

const UNKNOWN_FILE_BINDING: BindingApi = {
    ...GITHUB_BINDING,
    repository: 'git.example.com/platform/web-app',
    source: null,
    owned_fields: [],
}

const managedKinds = {
    results: [
        {
            kind: 'flag',
            stack_name: 'web-app',
            repository: 'example-org/web-app',
            definitions: 3,
            redirect_creates: true,
        },
    ],
}

const mocks = (
    binding: BindingApi,
    changeRequest: [number, Record<string, unknown>] = [201, { task_id: 'task-1', task_url: '/tasks/task-1' }]
): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/stacks/managed_kinds/': managedKinds,
            '/api/projects/:team_id/stacks/bindings/': { binding },
        },
        post: {
            '/api/projects/:team_id/stacks/:name/bindings/:id/detach/': { ...binding, status: 'detached' },
            '/api/projects/:team_id/stacks/:name/bindings/:id/change_requests/': () => changeRequest,
        },
    })

const meta: Meta<typeof ManagedInCodeBanner> = {
    title: 'Components/Managed in code banner',
    component: ManagedInCodeBanner,
    args: { kind: 'flag', entityId: 42 },
    decorators: [
        (Story) => (
            // A fixed width, so the banner wraps the same way on every run.
            <div className="w-[42rem]">
                <Story />
            </div>
        ),
    ],
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.POSTHOG_AS_CODE],
        testOptions: { waitForSelector: '[data-attr="managed-in-code-banner"]' },
    },
}
export default meta

type Story = StoryObj<typeof ManagedInCodeBanner>

const openDialog = async (button: string): Promise<ReturnType<typeof within>> => {
    const body = within(document.body)
    fireEvent.click(await body.findByRole('button', { name: button }))
    await body.findByRole('dialog')
    return body
}

const submitChange = async (): Promise<void> => {
    const body = await openDialog('Ask for a change')
    fireEvent.change(body.getByPlaceholderText(/For example/), {
        target: { value: 'Rename it to Checkout v2 and add the growth tag' },
    })
    fireEvent.click(body.getByRole('button', { name: 'Start task' }))
}

export const ManagedFromGitHub: Story = {
    decorators: [mocks(GITHUB_BINDING)],
}

export const ManagedWithoutKnownFile: Story = {
    decorators: [mocks(UNKNOWN_FILE_BINDING)],
}

export const DetachConfirmation: Story = {
    decorators: [mocks(GITHUB_BINDING)],
    parameters: { layout: 'fullscreen', testOptions: { waitForSelector: '.LemonModal' } },
    play: async () => {
        await openDialog('Detach')
    },
}

export const AskForChangeForm: Story = {
    decorators: [mocks(GITHUB_BINDING)],
    parameters: { layout: 'fullscreen', testOptions: { waitForSelector: '.LemonModal' } },
    play: async () => {
        await openDialog('Ask for a change')
    },
}

export const AskForChangeStarted: Story = {
    decorators: [mocks(GITHUB_BINDING)],
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForSelector: '[data-attr="managed-in-code-change-started"]' },
    },
    play: submitChange,
}

export const AskForChangeRepositoryNotConnected: Story = {
    decorators: [
        mocks(GITHUB_BINDING, [
            409,
            {
                type: 'invalid_request',
                code: 'repository_not_connected',
                detail: 'The repository has no GitHub connection.',
                attr: null,
            },
        ]),
    ],
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForSelector: '[data-attr="managed-in-code-change-connect-github"]' },
    },
    play: submitChange,
}

export const AskForChangeTasksUnavailable: Story = {
    decorators: [
        mocks(GITHUB_BINDING, [
            409,
            {
                type: 'invalid_request',
                code: 'tasks_unavailable',
                detail: 'This project cannot start cloud tasks.',
                attr: null,
            },
        ]),
    ],
    parameters: { layout: 'fullscreen', testOptions: { waitForSelector: "text=can't start cloud tasks" } },
    play: submitChange,
}
