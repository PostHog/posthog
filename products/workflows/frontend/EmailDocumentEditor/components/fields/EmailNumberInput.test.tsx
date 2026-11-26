import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import { EmailNumberInput } from './EmailNumberInput'

describe('EmailNumberInput', () => {
    let saved: (number | undefined)[]

    afterEach(cleanup)

    function Field({ start }: { start?: number }): JSX.Element {
        const [value, setValue] = useState<number | undefined>(start)
        return (
            <EmailNumberInput
                aria-label="Width"
                limit={{ min: 200, max: 1200 }}
                value={value}
                onChange={(next) => {
                    saved.push(next)
                    setValue(next)
                }}
            />
        )
    }

    function open(start?: number): HTMLInputElement {
        saved = []
        render(<Field start={start} />)
        const input = screen.getByLabelText<HTMLInputElement>('Width')
        fireEvent.focus(input)
        return input
    }

    it.each([
        ['5000', 1200, 'Set to the maximum: 1200px'],
        ['-20', 200, 'Set to the minimum: 200px'],
        ['0.5', 200, 'Set to the minimum: 200px'],
    ])('keeps %s as typed, then corrects it to %s and says so', (typed, corrected, message) => {
        const input = open(600)
        fireEvent.change(input, { target: { value: typed } })
        expect(saved).toEqual([])
        expect(input.value).toBe(typed)

        fireEvent.blur(input)
        expect(saved).toEqual([corrected])
        expect(input.value).toBe(String(corrected))
        expect(screen.getByRole('status').textContent).toBe(message)
    })

    it.each<[string, string[], (number | undefined)[]]>([
        ['a number on its way to a valid one', ['6', '64', '640'], [640]],
        ['a cleared field', [''], [undefined]],
        ['a cleared draft', ['5000', ''], [undefined]],
    ])('saves %s once it is valid', (_, steps, expected) => {
        const input = open(600)
        steps.forEach((value) => fireEvent.change(input, { target: { value } }))
        fireEvent.blur(input)
        expect(saved).toEqual(expected)
        expect(screen.queryByRole('status')).toBeNull()
    })

    it('leaves a saved number outside the limits alone and lets the form submit', () => {
        const input = open(5000)
        fireEvent.blur(input)
        expect(saved).toEqual([])
        expect(input.value).toBe('5000')
        expect(input.validity.valid).toBe(true)
    })

    it.each(['Enter', 'Escape'])('corrects on %s', (key) => {
        const input = open(600)
        fireEvent.change(input, { target: { value: '5000' } })
        fireEvent.keyDown(input, { key })
        expect(saved).toEqual([1200])
        fireEvent.blur(input)
        expect(saved).toEqual([1200])
    })
})
