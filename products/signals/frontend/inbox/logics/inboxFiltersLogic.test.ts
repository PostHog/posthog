import { MOCK_DEFAULT_USER } from 'lib/api.mock'

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

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
    stateFilter: ['monitoring', 'verifying', 'needs-decision'],
    sortField: 'priority',
    sortDirection: 'asc',
    searchQuery: '',
    createdWindow: null,
}

describe('inboxFiltersLogic', () => {
    describe('saved state filters', () => {
        beforeEach(() => {
            localStorage.clear()
            initKeaTests()
            useMocks({ get: { '/api/projects/:team_id/signals/reports/available_reviewers/': () => [200, {}] } })
        })

        it.each([
            [
                ['monitoring', 'needs-decision'],
                ['monitoring', 'verifying', 'needs-decision'],
            ],
            [['resolved'], ['resolved']],
            [[], []],
        ])('migrates only the saved default %s', (saved, expected) => {
            localStorage.setItem('scenes.inbox.logics.inboxFiltersLogic.stateFilter', JSON.stringify(saved))
            router.actions.push(urls.inbox())
            const logic = inboxFiltersLogic()
            logic.mount()
            try {
                expect(logic.values.stateFilter).toEqual(expected)
                expect(logic.values.stateFilterVersion).toBe(1)
            } finally {
                logic.unmount()
            }
        })

        it('keeps an explicit shared selection and does not migrate it on later mounts', () => {
            localStorage.setItem(
                'scenes.inbox.logics.inboxFiltersLogic.stateFilter',
                JSON.stringify(['monitoring', 'needs-decision'])
            )
            router.actions.push(urls.inbox(), { state: 'monitoring,needs-decision' })
            const logic = inboxFiltersLogic()
            logic.mount()
            expect(logic.values.stateFilter).toEqual(['monitoring', 'needs-decision'])
            logic.unmount()
            initKeaTests()
            router.actions.push(urls.inbox())
            const restored = inboxFiltersLogic()
            restored.mount()
            try {
                expect(restored.values.stateFilter).toEqual(['monitoring', 'needs-decision'])
            } finally {
                restored.unmount()
            }
        })

        it('allows deselecting Verifying after the migration without adding it back', () => {
            localStorage.setItem(
                'scenes.inbox.logics.inboxFiltersLogic.stateFilter',
                JSON.stringify(['monitoring', 'needs-decision'])
            )
            router.actions.push(urls.inbox())
            const logic = inboxFiltersLogic()
            logic.mount()
            logic.actions.toggleState('verifying')
            logic.unmount()
            initKeaTests()
            router.actions.push(urls.inbox())
            const restored = inboxFiltersLogic()
            restored.mount()
            try {
                expect(restored.values.stateFilter).toEqual(['monitoring', 'needs-decision'])
            } finally {
                restored.unmount()
            }
        })
    })
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

        it('leads with the ranking field for a model sort', () => {
            expect(buildSignalReportListOrdering('ranking_pr_merged', 'desc')).toBe(
                '-ranking_pr_merged,status,-updated_at'
            )
        })
    })

    describe('filter URL params', () => {
        // Keeps shared links clean: a default view must not carry any filter params.
        it('omits all default filters from the URL', () => {
            expect(filterSearchParams(DEFAULT_STATE)).toEqual({})
        })

        it.each<[string, InboxFilterState, Record<string, string>]>([
            [
                'scope + sources + scouts + priorities + states + custom sort + search',
                {
                    scope: 'entire-project',
                    sourceProductFilter: ['error_tracking', 'github'],
                    // Scout slugs are team-specific and dynamic, so they round-trip without a
                    // static valid-set check — unlike sources.
                    scoutFilter: ['signals-scout-error-tracking', 'my-custom-scout'],
                    priorityFilter: ['P0', 'P2'],
                    stateFilter: ['monitoring', 'resolved'],
                    sortField: 'created_at',
                    sortDirection: 'desc',
                    searchQuery: 'checkout crash',
                    createdWindow: null,
                },
                {
                    scope: 'entire-project',
                    source: 'error_tracking,github',
                    scout: 'signals-scout-error-tracking,my-custom-scout',
                    priority: 'P0,P2',
                    state: 'monitoring,resolved',
                    sort: 'created_at:desc',
                    search: 'checkout crash',
                },
            ],
            [
                'teammate scope only',
                { ...DEFAULT_STATE, scope: 'teammate:0199ed4a-5c03-0000-3220-df21df612e95' },
                { scope: 'teammate:0199ed4a-5c03-0000-3220-df21df612e95' },
            ],
            // An unchecked-everything selection means every state. It must survive the URL rewrite
            // that follows each toggle, or hydration would put the default selection straight back.
            ['an explicitly empty state selection', { ...DEFAULT_STATE, stateFilter: [] }, { state: 'all' }],
            ['a created-in window', { ...DEFAULT_STATE, createdWindow: '7d' }, { created: '7d' }],
        ])('round-trips %s through encode/decode', (_name, state, expectedParams) => {
            expect(filterSearchParams(state)).toEqual(expectedParams)
            expect(parseFilterSearchParams(expectedParams)).toEqual(state)
        })

        // A shared link is authoritative but untrusted: unknown values (a malformed teammate id, which would
        // otherwise reach the report-list API as a bad reviewer UUID, and a syntactically valid but
        // unsupported sort combination the Sort control can't display) must not leak into filter state.
        it('drops unknown sources, priorities, states, malformed teammate scope and unsupported sort', () => {
            expect(
                parseFilterSearchParams({
                    scope: 'teammate:not-a-uuid',
                    source: 'error_tracking,bogus_source',
                    priority: 'P9,P1',
                    state: 'monitoring,bogus-state',
                    // priority:desc has a valid field and direction but is not one of the offered sort options.
                    sort: 'priority:desc',
                })
            ).toEqual({
                ...DEFAULT_STATE,
                sourceProductFilter: ['error_tracking'],
                priorityFilter: ['P1'],
                stateFilter: ['monitoring'],
            })
        })

        it.each([
            ['keeps a model sort for a user who can use it', true, 'ranking_pr_merged', 'desc'],
            ['falls back to the default sort for a user who cannot', false, 'priority', 'asc'],
        ] as const)('%s', (_name, modelSortAvailable, sortField, sortDirection) => {
            expect(parseFilterSearchParams({ sort: 'ranking_pr_merged:desc' }, { modelSortAvailable })).toEqual({
                ...DEFAULT_STATE,
                sortField,
                sortDirection,
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

        // The flat Reports list has no `?view=` sub-view, so a query change on it must attribute to
        // the `reports` tab and agree with the `tab` that `Inbox viewed` sends for the same visit.
        it('attributes a redesigned Reports query change to the reports tab', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
                [FEATURE_FLAGS.INBOX_REDESIGN]: true,
            })
            router.actions.push(urls.inbox('reports'))
            logic.actions.toggleState('needs-decision')
            await expectLogic(logic).toFinishAllListeners()
            expect(queryChanges()).toEqual([expect.objectContaining({ change: 'state', tab: 'reports' })])
        })
    })

    describe('filter state', () => {
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

        it.each([{}, { search: 'trial search' }])('leaves trial URLs and inbox filters unchanged for %p', (params) => {
            logic.actions.setFilters({ ...DEFAULT_STATE, searchQuery: 'inbox search' })

            router.actions.push(urls.inboxScoutTrials(), params)

            expect(router.values.searchParams).toEqual(params)
            expect(logic.values.searchQuery).toBe('inbox search')
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

        it.each([
            ['keeps a stored model sort for staff with the flag', true, true, 'ranking_pr_merged', 'desc'],
            ['falls back to the default once the flag is off', false, true, 'priority', 'asc'],
            ['falls back to the default for a non-staff user', true, false, 'priority', 'asc'],
        ] as const)('%s', (_name, flagOn, isStaff, activeSortField, activeSortDirection) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_MODEL_SORT], {
                [FEATURE_FLAGS.INBOX_MODEL_SORT]: true,
            })
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: true })
            logic.actions.setSort('ranking_pr_merged', 'desc')

            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_MODEL_SORT], {
                [FEATURE_FLAGS.INBOX_MODEL_SORT]: flagOn,
            })
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })

            expect(logic.values).toMatchObject({
                sortField: 'ranking_pr_merged',
                activeSortField,
                activeSortDirection,
            })
        })
    })
})
