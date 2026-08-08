import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'

import { FilterPill } from './FilterPill'

describe('FilterPill', () => {
    afterEach(() => cleanup())

    it.each([
        { name: 'loading with no options', loading: true, expected: 'Loading…' },
        { name: 'empty with no options', loading: false, expected: 'No options' },
    ])('shows a placeholder instead of an empty popover: $name', async ({ loading, expected }) => {
        const { container } = render(
            <FilterPill<string> label="Created by" options={[]} value={[]} onChange={jest.fn()} loading={loading} />
        )

        fireEvent.click(within(container).getByRole('button'))

        // findByText throws if the placeholder never renders, which is the regression we guard against.
        expect(await screen.findByText(expected)).toBeTruthy()
    })
})
