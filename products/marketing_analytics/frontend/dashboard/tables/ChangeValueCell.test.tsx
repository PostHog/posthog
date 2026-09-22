import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { CurrencyCode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ChangeValueCell } from './ChangeValueCell'

describe('ChangeValueCell', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([
        [CurrencyCode.USD, -12.5, -10, '-$12.50', '-$2.50'],
        [CurrencyCode.EUR, -1250, -1200, '-€1,250', '-€50.00'],
    ] as const)(
        'places the sign before %s for negative values and changes',
        (currency, current, previous, value, delta) => {
            render(<ChangeValueCell currency={currency} value={[current, previous]} kind="currency" compare />)

            expect(screen.getByText(value)).toBeInTheDocument()
            expect(screen.getByText(delta)).toBeInTheDocument()
        }
    )

    it('shows a change from a zero baseline but hides an unavailable comparison', () => {
        const { rerender } = render(
            <ChangeValueCell currency={CurrencyCode.USD} value={[12.5, 0]} kind="currency" compare />
        )

        expect(screen.getByText('+$12.50')).toBeInTheDocument()

        rerender(<ChangeValueCell currency={CurrencyCode.USD} value={[12.5, null]} kind="currency" compare />)

        expect(screen.getByText('$12.50')).toBeInTheDocument()
        expect(screen.queryByText('+$12.50')).not.toBeInTheDocument()
    })
})
