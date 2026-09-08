import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { HogFlowDuration } from './HogFlowDuration'

describe('HogFlowDuration', () => {
    afterEach(cleanup)

    it('keeps the unit and does not fall back to a default when the number is cleared', () => {
        const onChange = jest.fn()
        render(<HogFlowDuration value="3d" onChange={onChange} />)

        const input = screen.getByRole('spinbutton')
        fireEvent.change(input, { target: { value: '' } })

        // Clearing must preserve the unit (days) and must not reset the number to a default like "10m"
        expect(onChange).toHaveBeenCalledWith('d')
    })

    it('renders an empty field instead of a default number when the value has no number', () => {
        render(<HogFlowDuration value="d" onChange={jest.fn()} />)
        expect(screen.getByRole('spinbutton')).toHaveValue(null)
    })

    it('renders a stored fractional value as-is', () => {
        // A duration set over the API (e.g. "1.5d") used to be rounded down on display, silently
        // rewriting the delay the next time anyone opened the step.
        render(<HogFlowDuration value="1.5d" onChange={jest.fn()} />)
        expect(screen.getByRole('spinbutton')).toHaveValue(1.5)
    })

    it('keeps a fractional value typed into the input', () => {
        const onChange = jest.fn()
        render(<HogFlowDuration value="3d" onChange={onChange} />)

        const input = screen.getByRole('spinbutton')
        fireEvent.change(input, { target: { value: '2.7' } })

        expect(onChange).toHaveBeenCalledWith('2.7d')
    })

    it('holds the committed duration while the field holds an unparseable draft', () => {
        const onChange = jest.fn()
        render(<HogFlowDuration value="1d" onChange={onChange} />)

        const input = screen.getByRole('spinbutton')
        // A number input blanks its value and reports NaN for a draft it cannot parse, such as the
        // lone "." that starts ".5", and flags it only through validity.badInput. jsdom does not
        // model badInput, so stand it in to reach the branch a real browser takes.
        Object.defineProperty(input, 'validity', { value: { badInput: true }, configurable: true })
        fireEvent.change(input, { target: { value: '' } })

        // Writing a unit with no number here replaces a valid duration with one that fails validation
        expect(onChange).not.toHaveBeenCalled()
    })

    it('emits a fixed-point amount for a value that would stringify as an exponent', () => {
        const onChange = jest.fn()
        render(<HogFlowDuration value="1d" onChange={onChange} />)

        fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0.0000001' } })

        // "1e-7d" matches none of the duration parsers in the stack
        expect(onChange).toHaveBeenCalledWith('0d')
    })

    it('renders a stored seconds duration with its unit', () => {
        render(<HogFlowDuration value="45s" onChange={jest.fn()} />)
        expect(screen.getByRole('spinbutton')).toHaveValue(45)
        expect(screen.getByText('Second(s)')).toBeInTheDocument()
    })

    it.each([
        ['holds a day amount to the 30-day ceiling on blur by default', false, '30d'],
        ['keeps a day amount past the ceiling on blur when unbounded', true, '45d'],
    ])('%s', (_name, allowUnbounded, expected) => {
        const onChange = jest.fn()
        render(<HogFlowDuration value="45d" onChange={onChange} allowUnbounded={allowUnbounded as boolean} />)

        fireEvent.blur(screen.getByRole('spinbutton'))

        expect(onChange).toHaveBeenCalledWith(expected)
    })

    it('clears the field immediately on change even before the parent commits the new value', () => {
        render(<HogFlowDuration value="2h" onChange={jest.fn()} />)

        const input = screen.getByRole('spinbutton')
        expect(input).toHaveValue(2)
        fireEvent.change(input, { target: { value: '' } })

        // The parent commits config through an async listener, so value is still "2h" here. The field must
        // read empty rather than snapping back to 2 (the swallowed-keystroke regression).
        expect(input).toHaveValue(null)
    })
})
