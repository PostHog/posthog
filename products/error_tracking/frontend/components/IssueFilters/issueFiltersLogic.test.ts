import { Params } from 'scenes/sceneTypes'

import { FilterLogicalOperator } from '~/types'

import {
    DEFAULT_DATE_RANGE,
    DEFAULT_TEST_ACCOUNT,
    IssueFilterActions,
    isValidDateRange,
    triggerFilterActions,
} from './issueFiltersLogic'

describe('issueFiltersLogic helpers', () => {
    describe('isValidDateRange', () => {
        const cases: Array<[string, unknown, boolean]> = [
            ['valid object with relative date_from', { date_from: '-7d', date_to: null }, true],
            ['valid object with absolute date_from', { date_from: '2026-04-01', date_to: '2026-04-29' }, true],
            ['raw string from URL like ?dateRange=7d', '7d', false],
            ['null', null, false],
            ['undefined', undefined, false],
            ['array', ['-7d', null], false],
            ['object missing date_from', { date_to: null }, false],
            ['object with non-string date_from', { date_from: 7 }, false],
        ]

        it.each(cases)('returns %s for: %s', (_label, input, expected) => {
            expect(isValidDateRange(input)).toBe(expected)
        })
    })

    describe('triggerFilterActions', () => {
        const baseValues = {
            dateRange: DEFAULT_DATE_RANGE,
            filterGroup: { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values: [] }] },
            filterTestAccounts: DEFAULT_TEST_ACCOUNT,
            searchQuery: '',
        }

        function makeActions(): jest.Mocked<IssueFilterActions> {
            return {
                setDateRange: jest.fn(),
                setSearchQuery: jest.fn(),
                setFilterGroup: jest.fn(),
                setFilterTestAccounts: jest.fn(),
            }
        }

        it('falls back to DEFAULT_DATE_RANGE when params.dateRange is the malformed string "7d"', () => {
            const actions = makeActions()
            const params: Params = { dateRange: '7d' }
            triggerFilterActions(params, { ...baseValues, dateRange: { date_from: '-1d', date_to: null } }, actions)
            expect(actions.setDateRange).toHaveBeenCalledWith(DEFAULT_DATE_RANGE)
        })

        it('does not call setDateRange when current value already equals fallback', () => {
            const actions = makeActions()
            const params: Params = { dateRange: '7d' }
            triggerFilterActions(params, baseValues, actions)
            expect(actions.setDateRange).not.toHaveBeenCalled()
        })

        it('passes through a valid dateRange object', () => {
            const actions = makeActions()
            const validRange = { date_from: '-30d', date_to: null }
            triggerFilterActions({ dateRange: validRange }, baseValues, actions)
            expect(actions.setDateRange).toHaveBeenCalledWith(validRange)
        })
    })
})
