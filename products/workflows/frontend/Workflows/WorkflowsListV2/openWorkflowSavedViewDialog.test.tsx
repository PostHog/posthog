import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, screen, waitFor, waitForElementToBeRemoved } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { openDeleteWorkflowSavedViewDialog, openWorkflowSavedViewDialog } from './openWorkflowSavedViewDialog'

describe('saved workflow view dialog', () => {
    beforeEach(() => initKeaTests())

    afterEach(async () => {
        const cancel = screen.queryByText('Cancel')
        if (cancel) {
            const removed = waitForElementToBeRemoved(screen.getByRole('textbox'))
            await userEvent.click(cancel)
            await removed
        }
        cleanup()
    })

    it('shares one pending submit across repeated Enter presses and retains the name after failure', async () => {
        let fail: ((error: Error) => void) | undefined
        const pending = new Promise<void>((_, reject) => {
            fail = reject
        })
        const submit = jest
            .fn()
            .mockImplementationOnce(() => pending)
            .mockResolvedValue(undefined)
        act(() => openWorkflowSavedViewDialog(submit))
        const input = await screen.findByRole('textbox')
        await userEvent.type(input, 'Shared draft')
        await userEvent.keyboard('{Enter}{Enter}')
        expect(submit).toHaveBeenCalledTimes(1)
        await act(async () => {
            fail!(new ApiError('Name unavailable', 400))
        })
        expect(input).toBeInTheDocument()
        expect(input).toHaveValue('Shared draft')
        await userEvent.keyboard('{Enter}')
        await waitFor(() => expect(screen.queryByRole('textbox')).not.toBeInTheDocument())
        expect(submit.mock.calls).toEqual([['Shared draft'], ['Shared draft']])
    })

    it('deletes a shared view only after the user confirms that everyone loses it', async () => {
        const remove = jest.fn().mockResolvedValue(undefined)
        act(() => openDeleteWorkflowSavedViewDialog('Active flows', remove))
        expect(await screen.findByText('Delete Active flows?')).toBeInTheDocument()
        expect(screen.getByText('Everyone in this project loses this view.')).toBeInTheDocument()
        await userEvent.click(screen.getByText('Cancel'))
        await waitFor(() => expect(screen.queryByText('Delete Active flows?')).not.toBeInTheDocument())
        expect(remove).not.toHaveBeenCalled()

        act(() => openDeleteWorkflowSavedViewDialog('Active flows', remove))
        await userEvent.click(await screen.findByText('Delete view'))
        await waitFor(() => expect(screen.queryByText('Delete Active flows?')).not.toBeInTheDocument())
        expect(remove).toHaveBeenCalledTimes(1)
    })

    it('does not submit when Enter confirms an IME composition', async () => {
        const submit = jest.fn().mockResolvedValue(undefined)
        act(() => openWorkflowSavedViewDialog(submit, 'Shared draft'))
        const input = await screen.findByRole('textbox')
        fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
        expect(submit).not.toHaveBeenCalled()
        expect(input).toHaveValue('Shared draft')
        await userEvent.click(input)
        await userEvent.keyboard('{Enter}')
        await waitFor(() => expect(screen.queryByRole('textbox')).not.toBeInTheDocument())
        expect(submit).toHaveBeenCalledWith('Shared draft')
    })
})
