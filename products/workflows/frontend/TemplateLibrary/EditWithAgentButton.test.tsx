import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EditWithAgentButton } from './EditWithAgentButton'
import { messageTemplateLogic } from './messageTemplateLogic'
import { QuillEditWithAgentButton } from './QuillEditWithAgentButton'

const CODE_MANAGED = {
    id: 'existing-id',
    name: 'Welcome',
    content: { templating: 'liquid', email: { subject: 'Welcome', html: '<p>Hi</p>', text: '' } },
    key: 'welcome',
    managed_by: 'code',
    source_path: 'emails/welcome.html',
    change_prompt_starter: 'In `emails/welcome.html`, change ',
    change_prompt_context: 'About this file:\n- It is the PostHog email template with the key `welcome`.',
    change_prompt_variables: [],
}

describe.each([
    { name: 'EditWithAgentButton', Button: EditWithAgentButton },
    { name: 'QuillEditWithAgentButton', Button: QuillEditWithAgentButton },
])('$name', ({ Button }) => {
    beforeEach(async () => {
        useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': CODE_MANAGED } })
        initKeaTests()
        const logic = messageTemplateLogic({ id: 'existing-id' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
        render(
            <Provider>
                <Button id="existing-id" />
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { closedBy: 'Escape', close: (user: ReturnType<typeof userEvent.setup>) => user.keyboard('{Escape}') },
        {
            closedBy: 'a second click on the button',
            close: (user: ReturnType<typeof userEvent.setup>) =>
                user.click(screen.getByText('Edit with your agent').closest('button') as HTMLButtonElement),
        },
        {
            closedBy: 'Escape with focus on the button',
            close: async (user: ReturnType<typeof userEvent.setup>) => {
                ;(screen.getByText('Edit with your agent').closest('button') as HTMLButtonElement).focus()
                await user.keyboard('{Escape}')
            },
        },
        {
            closedBy: 'Copy prompt',
            close: async (user: ReturnType<typeof userEvent.setup>) => {
                await user.keyboard(' the button to green')
                await user.click(screen.getByText('Copy prompt'))
            },
        },
    ])('gives focus back to the button when $closedBy closes the prompt', async ({ close }) => {
        const user = userEvent.setup()
        const trigger = screen.getByText('Edit with your agent').closest('button') as HTMLButtonElement

        await user.click(trigger)
        await waitFor(() => expect(screen.getByLabelText('Describe the change')).toHaveFocus())
        expect(trigger).toHaveAttribute('aria-expanded', 'true')

        await close(user)

        await waitFor(() => expect(screen.queryByLabelText('Describe the change')).not.toBeInTheDocument())
        expect(trigger).toHaveAttribute('aria-expanded', 'false')
        expect(trigger).toHaveFocus()
    })

    it.each([
        { keys: 'Cmd+Enter', shiftKey: false, isComposing: false, copies: true },
        { keys: 'Cmd+Enter during an IME composition', shiftKey: false, isComposing: true, copies: false },
        { keys: 'Shift+Cmd+Enter', shiftKey: true, isComposing: false, copies: false },
    ])('$keys copies the prompt: $copies', async ({ shiftKey, isComposing, copies }) => {
        const user = userEvent.setup()
        await user.click(screen.getByText('Edit with your agent').closest('button') as HTMLButtonElement)
        await waitFor(() => expect(screen.getByLabelText('Describe the change')).toHaveFocus())
        await user.keyboard(' the button to green')

        fireEvent.keyDown(screen.getByLabelText('Describe the change'), {
            key: 'Enter',
            metaKey: true,
            shiftKey,
            isComposing,
        })

        const logic = messageTemplateLogic({ id: 'existing-id' })
        if (copies) {
            await expectLogic(logic).toDispatchActions(['copyAgentPrompt'])
        } else {
            await expectLogic(logic).toNotHaveDispatchedActions(['copyAgentPrompt'])
        }
    })
})
