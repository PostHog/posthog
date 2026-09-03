import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { HotkeyRadio } from './HotkeyRadio'

describe('HotkeyRadio', () => {
    const options = [
        { value: 'one', label: 'First' },
        { value: 'two', label: 'Second' },
        { value: 'three', label: 'Third' },
    ] as const

    afterEach(cleanup)

    function renderRadio(): jest.Mock {
        const onChange = jest.fn()
        render(
            <div>
                <HotkeyRadio value={null} onChange={onChange} options={options} />
                <textarea aria-label="note" />
            </div>
        )
        return onChange
    }

    it.each<[string, () => Promise<void>, string | null]>([
        [
            'a digit picks the matching option',
            async () => {
                await userEvent.keyboard('2')
            },
            'two',
        ],
        // The regression this guards: a digit typed into the note must not change the reason.
        [
            'a digit typed into a text field is left alone',
            async () => {
                await userEvent.click(screen.getByLabelText('note'))
                await userEvent.keyboard('2')
            },
            null,
        ],
        // A radio already holds focus after a click, and a digit must still switch the choice.
        [
            'a digit still picks after a radio was clicked',
            async () => {
                await userEvent.click(screen.getByLabelText(/First/))
                await userEvent.keyboard('3')
            },
            'three',
        ],
        [
            'a digit past the last option does nothing',
            async () => {
                await userEvent.keyboard('4')
            },
            null,
        ],
        // Command/Ctrl+digit is a browser tab switch, not a pick.
        [
            'a modifier chord is left to the browser',
            async () => {
                await userEvent.keyboard('{Meta>}2{/Meta}')
            },
            null,
        ],
    ])('%s', async (_name, press, expected) => {
        const onChange = renderRadio()
        await press()
        if (expected === null) {
            expect(onChange).not.toHaveBeenCalled()
        } else {
            expect(onChange).toHaveBeenLastCalledWith(expected)
        }
    })

    it('shows the digit keycap in front of each option', () => {
        renderRadio()
        expect(screen.getByLabelText(/Second/)).toBeInTheDocument()
        expect(screen.getByText('2')).toBeInTheDocument()
    })
})
