import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'

import { ScoutNewButton } from './ScoutNewButton'

// The two ways to create a scout. Check the menu, the chat modal as it fills and submits, and the
// form with its link back to the chat. The layout must hold in a scene about 520px wide.

const meta: Meta<typeof ScoutNewButton> = {
    title: 'Scenes-App/Inbox/ScoutNewButton',
    component: ScoutNewButton,
    parameters: {
        layout: 'centered',
        testOptions: { waitForLoadersToDisappear: false },
    },
    args: { surface: 'fleet_list' },
    decorators: [
        (Story) => (
            <div className="flex w-[520px] justify-end gap-2">
                <Story />
            </div>
        ),
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs/': () => [200, []],
            },
            post: {
                // Never answers, so the submitting story holds its loading state.
                '/api/projects/:id/signals/scout/chat_tasks/': () => new Promise(() => {}),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ScoutNewButton>

async function waitForElement(selector: string): Promise<void> {
    await waitFor(() => {
        if (!document.querySelector(selector)) {
            throw new Error(`${selector} not rendered yet`)
        }
    })
}

async function openChatModal(canvasElement: HTMLElement): Promise<void> {
    await userEvent.click(await within(canvasElement).findByText('New scout'))
    await waitForElement('[data-attr="scout-new-chat"]')
    await userEvent.click(document.querySelector<HTMLElement>('[data-attr="scout-new-chat"]')!)
    await waitForElement('[data-attr="scout-chat-prompt"]')
}

export const Menu: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.Popover' } },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('New scout'))
        await waitForElement('.Popover')
    },
}

export const EmptyStateButtons: Story = {
    args: { layout: 'buttons', surface: 'empty_state' },
}

export const ChatModalEmpty: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.LemonModal' } },
    play: async ({ canvasElement }) => {
        await openChatModal(canvasElement)
    },
}

export const ChatModalTemplatePicked: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.LemonModal' } },
    play: async ({ canvasElement }) => {
        await openChatModal(canvasElement)
        await userEvent.click(document.querySelector<HTMLElement>('[data-attr="scout-chat-template-spam_signups"]')!)
    },
}

export const ChatModalSubmitting: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.LemonModal' } },
    play: async ({ canvasElement }) => {
        await openChatModal(canvasElement)
        await userEvent.click(document.querySelector<HTMLElement>('[data-attr="scout-chat-template-new_errors"]')!)
        await userEvent.click(document.querySelector<HTMLElement>('[data-attr="scout-chat-start"]')!)
    },
}

export const FormWithChatLink: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.LemonModal' } },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('New scout'))
        await waitForElement('[data-attr="scout-new-form"]')
        await userEvent.click(document.querySelector<HTMLElement>('[data-attr="scout-new-form"]')!)
        await waitForElement('[data-attr="scout-create-use-chat"]')
    },
}
