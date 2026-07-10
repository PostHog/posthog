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

    it('floors a stored decimal value on display so old data upgrades to a whole number', () => {
        render(<HogFlowDuration value="1.5d" onChange={jest.fn()} />)
        expect(screen.getByRole('spinbutton')).toHaveValue(1)
    })

    it('floors a fractional value emitted by the input to a whole number', () => {
        const onChange = jest.fn()
        render(<HogFlowDuration value="3d" onChange={onChange} />)

        const input = screen.getByRole('spinbutton')
        fireEvent.change(input, { target: { value: '2.7' } })

        expect(onChange).toHaveBeenCalledWith('2d')
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
