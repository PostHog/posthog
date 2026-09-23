import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { SubscriptionTimePicker } from './SubscriptionTimePicker'

describe('SubscriptionTimePicker', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-09-01T12:00:00Z'))
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('offers half-hour times without changing the existing date-anchor behavior', () => {
        const onChange = jest.fn()

        render(<SubscriptionTimePicker value="2024-01-01T09:00:00Z" onChange={onChange} />)

        fireEvent.click(screen.getByLabelText('Delivery time'))

        expect(screen.queryByText('9:15 AM')).not.toBeInTheDocument()
        fireEvent.click(screen.getByText('9:30 AM'))

        expect(onChange).toHaveBeenCalledWith('2026-09-01T09:30:00.000Z')
    })
})
