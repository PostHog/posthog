import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IssueEventsEmptyState } from './IssueEventsEmptyState'

describe('IssueEventsEmptyState', () => {
    afterEach(() => cleanup())

    it.each([
        { nextDateRangeLabel: '30 days', hasActiveFilters: true, dateButton: true, filterButton: true },
        { nextDateRangeLabel: '30 days', hasActiveFilters: false, dateButton: true, filterButton: false },
        { nextDateRangeLabel: null, hasActiveFilters: true, dateButton: false, filterButton: true },
        { nextDateRangeLabel: null, hasActiveFilters: false, dateButton: false, filterButton: false },
    ])(
        'shows the relevant recovery actions for $nextDateRangeLabel and filters=$hasActiveFilters',
        ({ nextDateRangeLabel, hasActiveFilters, dateButton, filterButton }) => {
            render(
                <IssueEventsEmptyState
                    nextDateRangeLabel={nextDateRangeLabel}
                    hasActiveFilters={hasActiveFilters}
                    loading={false}
                    onIncreaseDateRange={jest.fn()}
                    onClearFilters={jest.fn()}
                />
            )

            expect(Boolean(screen.queryByText(/Show last/))).toBe(dateButton)
            expect(Boolean(screen.queryByText('Remove filters'))).toBe(filterButton)
        }
    )

    it('runs the recovery actions', async () => {
        const onIncreaseDateRange = jest.fn()
        const onClearFilters = jest.fn()

        render(
            <IssueEventsEmptyState
                nextDateRangeLabel="30 days"
                hasActiveFilters
                loading={false}
                onIncreaseDateRange={onIncreaseDateRange}
                onClearFilters={onClearFilters}
            />
        )

        await userEvent.click(screen.getByText('Show last 30 days'))
        await userEvent.click(screen.getByText('Remove filters'))

        expect(onIncreaseDateRange).toHaveBeenCalledTimes(1)
        expect(onClearFilters).toHaveBeenCalledTimes(1)
    })
})
