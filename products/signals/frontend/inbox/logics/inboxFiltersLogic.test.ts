/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { INBOX_EVENTS } from '../inboxAnalytics'
import {
    buildSignalReportListOrdering,
    filterSearchParams,
    inboxFiltersLogic,
    InboxFilterState,
    parseFilterSearchParams,
} from './inboxFiltersLogic'

jest.mock('posthog-js')

const DEFAULT_STATE: InboxFilterState = {
    scope: 'for-you',
    sourceProductFilter: [],
    scoutFilter: [],
    priorityFilter: [],
    sortField: 'priority',
    sortDirection: 'asc',
    searchQuery: '',
}

describe('inboxFiltersLogic', () => {
    describe('buildSignalReportListOrdering', () => {
        it('leads with the selected time field so "Newest first" surfaces the newest reports', () => {
            // The list is flat, so created_at must be the primary key — not a sub-sort within status buckets.
            expect(buildSignalReportListOrdering('created_at', 'desc')).toBe('-created_at,status,-updated_at')
        })

        it('leads with created_at ascending for "Oldest first"', () => {
            expect(buildSignalReportListOrdering('created_at', 'asc')).toBe('created_at,status,-updated_at')
        })

        it('leads with updated_at and drops the redundant tiebreak for "Last updated first"', () => {
            expect(buildSignalReportListOrdering('updated_at', 'desc')).toBe('-updated_at,status')
        })

        it('leads with priority for "Priority first"', () => {
            expect(buildSignalReportListOrdering('priority', 'asc')).toBe('priority,status,-updated_at')
        })
    })

    describe('filter URL params', () => {
        // Keeps shared links clean: a default view must not carry any filter params.
        it('omits all default filters from the URL', () => {
            expect(filterSearchParams(DEFAULT_STATE)).toEqual({})
        })

        it.each<[string, InboxFilterState, Record<string, string>]>([
            [
                'scope + sources + scouts + priorities + custom sort + search',
                {
                    scope: 'entire-project',
                    sourceProductFilter: ['error_tracking', 'github'],
                    // Scout slugs are team-specific and dynamic, so they round-trip without a
                    // static valid-set check — unlike sources.
                    scoutFilter: ['signals-scout-error-tracking', 'my-custom-scout'],
                    priorityFilter: ['P0', 'P2'],
                    sortField: 'created_at',
                    sortDirection: 'desc',
                    searchQuery: 'checkout crash',
                },
                {
                    scope: 'entire-project',
                    source: 'error_tracking,github',
                    scout: 'signals-scout-error-tracking,my-custom-scout',
                    priority: 'P0,P2',
                    sort: 'created_at:desc',
                    search: 'checkout crash',
                },
            ],
            [
                'teammate scope only',
                { ...DEFAULT_STATE, scope: 'teammate:0199ed4a-5c03-0000-3220-df21df612e95' },
                { scope: 'teammate:0199ed4a-5c03-0000-3220-df21df612e95' },
            ],
        ])('round-trips %s through encode/decode', (_name, state, expectedParams) => {
            expect(filterSearchParams(state)).toEqual(expectedParams)
            expect(parseFilterSearchParams(expectedParams)).toEqual(state)
        })

        // A shared link is authoritative but untrusted: unknown values (a malformed teammate id, which would
        // otherwise reach the report-list API as a bad reviewer UUID, and a syntactically valid but
        // unsupported sort combination the Sort control can't display) must not leak into filter state.
        it('drops unknown sources, priorities, malformed teammate scope and unsupported sort', () => {
            expect(
                parseFilterSearchParams({
                    scope: 'teammate:not-a-uuid',
                    source: 'error_tracking,bogus_source',
                    priority: 'P9,P1',
                    // priority:desc has a valid field and direction but is not one of the offered sort options.
                    sort: 'priority:desc',
                })
            ).toEqual({
                ...DEFAULT_STATE,
                sourceProductFilter: ['error_tracking'],
                priorityFilter: ['P1'],
            })
        })
    })

    describe('query-changed telemetry', () => {
        let logic: ReturnType<typeof inboxFiltersLogic.build>

        const queryChanges = (): Record<string, any>[] =>
            (posthog.capture as jest.Mock).mock.calls
                .filter(([name]) => name === INBOX_EVENTS.QUERY_CHANGED)
                .map(([, props]) => props)

        beforeEach(() => {
            // Filter state persists to localStorage, which jsdom keeps between tests.
            localStorage.clear()
            initKeaTests()
            useMocks({ get: { '/api/projects/:team_id/signals/reports/available_reviewers/': () => [200, {}] } })
            ;(posthog.capture as jest.Mock).mockClear()
            logic = inboxFiltersLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it('reports a user-picked scope with the resulting query', async () => {
            logic.actions.setScope('entire-project')
            await expectLogic(logic).toFinishAllListeners()
            expect(queryChanges()).toEqual([
                expect.objectContaining({ change: 'scope', scope: 'entire-project', has_search: false }),
            ])
        })

        // The empty-inbox auto-default picks a scope for the user. Counting it as engagement would
        // fire this event for everyone who merely lands on an empty inbox — the exact inflation that
        // makes `Inbox viewed` unusable as an activity signal.
        it('stays silent when the scope is defaulted rather than chosen', async () => {
            logic.actions.applyDefaultScope('entire-project')
            await expectLogic(logic).toFinishAllListeners()
            expect(queryChanges()).toEqual([])
        })

        it('collapses a typed search into one event once the box settles', async () => {
            logic.actions.setSearchQuery('che')
            logic.actions.setSearchQuery('checkout')
            await expectLogic(logic).toFinishAllListeners()
            expect(queryChanges()).toEqual([
                expect.objectContaining({ change: 'search', has_search: true, search_length: 8 }),
            ])
        })
    })

    describe('scout filters', () => {
        let logic: ReturnType<typeof inboxFiltersLogic.build>

        beforeEach(() => {
            localStorage.clear()
            initKeaTests()
            useMocks({ get: { '/api/projects/:team_id/signals/reports/available_reviewers/': () => [200, {}] } })
            logic = inboxFiltersLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it('clears scouts without resetting the other filters', () => {
            logic.actions.setFilters({
                ...DEFAULT_STATE,
                sourceProductFilter: ['error_tracking'],
                scoutFilter: ['error-tracking-scout', 'ci-flakes-scout'],
                priorityFilter: ['P1'],
                searchQuery: 'checkout',
            })

            expectLogic(logic, () => logic.actions.clearScoutFilter()).toMatchValues({
                sourceProductFilter: ['error_tracking'],
                scoutFilter: [],
                priorityFilter: ['P1'],
                searchQuery: 'checkout',
            })
        })
    })
})
