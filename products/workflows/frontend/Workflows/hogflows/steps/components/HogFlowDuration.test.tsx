import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { HogFlowDuration } from './HogFlowDuration'

describe('HogFlowDuration', () => {
    afterEach(cleanup)

    const getNumberInput = (container: HTMLElement): HTMLInputElement =>
        container.querySelector('input[type="number"]') as HTMLInputElement

    it('keeps the unit and does not emit a value while the number field is cleared mid-edit', () => {
        const onChange = jest.fn()
        const { container } = render(<HogFlowDuration value="2h" onChange={onChange} />)

        // Backspacing the number field empty used to snap the unit back to minutes and
        // reset the number via the DURATION_REGEX fallback.
        fireEvent.change(getNumberInput(container), { target: { value: '' } })

        expect(screen.getByText('Hour(s)')).toBeInTheDocument()
        expect(onChange).not.toHaveBeenCalled()
    })

    it('normalizes an empty field to 0 on blur, preserving the unit', () => {
        const onChange = jest.fn()
        const { container } = render(<HogFlowDuration value="2h" onChange={onChange} />)

        const input = getNumberInput(container)
        fireEvent.change(input, { target: { value: '' } })
        fireEvent.blur(input)

        expect(onChange).toHaveBeenCalledWith('0h')
    })

    it('clamps to the per-unit max on blur', () => {
        const onChange = jest.fn()
        const { container } = render(<HogFlowDuration value="2h" onChange={onChange} />)

        const input = getNumberInput(container)
        fireEvent.change(input, { target: { value: '99' } })
        fireEvent.blur(input)

        expect(onChange).toHaveBeenCalledWith('24h')
    })
})
