import '@testing-library/jest-dom'

import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { SignalReportRefundReasonEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { openRefundReportDialog, RefundReportDialogResult } from './RefundReportDialog'

describe('openRefundReportDialog', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        document.body.innerHTML = ''
    })

    it.each([
        ['Enter', '{Enter}'],
        ['Shift+Enter', '{Shift>}{Enter}{/Shift}'],
    ])('inserts a newline on %s instead of submitting the refund', async (_, keys) => {
        const onConfirm = jest.fn<Promise<void>, [RefundReportDialogResult]>().mockResolvedValue(undefined)
        act(() => openRefundReportDialog({ reportTitle: 'A report', onConfirm }))

        await userEvent.click(await screen.findByText('Duplicate of work already covered'))
        const note = screen.getByPlaceholderText('Optional: add detail')
        await userEvent.click(note)
        await userEvent.keyboard('first line')
        await userEvent.keyboard(keys)
        await userEvent.keyboard('second line')

        expect(onConfirm).not.toHaveBeenCalled()
        expect(note).toHaveValue('first line\nsecond line')

        await userEvent.click(screen.getByText('Refund'))

        await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1))
        expect(onConfirm).toHaveBeenCalledWith({
            reason: SignalReportRefundReasonEnumApi.Duplicate,
            note: 'first line\nsecond line',
        })
    })
})
