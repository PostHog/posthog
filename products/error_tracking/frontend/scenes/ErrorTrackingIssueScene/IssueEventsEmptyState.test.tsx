import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IssueEventsEmptyState } from './IssueEventsEmptyState'

describe('IssueEventsEmptyState', () => {
    afterEach(() => cleanup())

    it.each([
        { nextDateRangeLabel: '30 days', hasActiveFilters: true, paused: false, dateButton: true, filterButton: true },
        {
            nextDateRangeLabel: '30 days',
            hasActiveFilters: false,
            paused: false,
            dateButton: true,
            filterButton: false,
        },
        { nextDateRangeLabel: null, hasActiveFilters: true, paused: false, dateButton: false, filterButton: true },
        { nextDateRangeLabel: null, hasActiveFilters: false, paused: false, dateButton: false, filterButton: false },
        { nextDateRangeLabel: '30 days', hasActiveFilters: true, paused: true, dateButton: false, filterButton: true },
    ])(
        'shows the relevant recovery actions for $nextDateRangeLabel, filters=$hasActiveFilters and paused=$paused',
        ({ nextDateRangeLabel, hasActiveFilters, paused, dateButton, filterButton }) => {
            render(
                <IssueEventsEmptyState
                    nextDateRangeLabel={nextDateRangeLabel}
                    hasActiveFilters={hasActiveFilters}
                    loading={false}
                    onIncreaseDateRange={jest.fn()}
                    onClearFilters={jest.fn()}
                    linkedLogsCheck={
                        paused ? { status: 'paused', checkedCount: 10_000, onCheckOlder: jest.fn() } : undefined
                    }
                />
            )

            expect(Boolean(screen.queryByText(/Show last/))).toBe(dateButton)
            expect(Boolean(screen.queryByText('Remove filters'))).toBe(filterButton)
            expect(Boolean(screen.queryByText('Check older exceptions'))).toBe(paused)
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
