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
})
