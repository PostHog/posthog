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
    appliedInboxSearch,
    buildSignalReportListOrdering,
    buildSignalReportListSortParams,
    filterSearchParams,
    inboxFiltersLogic,
    InboxFilterState,
    InboxSortField,
    parseFilterSearchParams,
} from './inboxFiltersLogic'

jest.mock('posthog-js')

const DEFAULT_STATE: InboxFilterState = {
    scope: 'for-you',
    sourceProductFilter: [],
    scoutFilter: [],
    priorityFilter: [],
    stateFilter: ['monitoring', 'needs-decision'],
    sortField: 'recommended',
    sortDirection: 'asc',
    searchQuery: '',
    createdWindow: null,
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

        it('leads with the ranking field for a model sort', () => {
            expect(buildSignalReportListOrdering('ranking_fix', 'desc')).toBe('-ranking_fix,status,-updated_at')
        })

        // The server ignores the `sort` preset whenever `ordering` is present.
        it.each([
            ['recommended', 'asc', { sort: 'recommended' }],
            ['priority', 'asc', { ordering: 'priority,status,-updated_at' }],
        ] as const)('sends %s:%s as %p', (field, direction, expected) => {
            expect(buildSignalReportListSortParams(field, direction)).toEqual(expected)
        })
    })

    describe('appliedInboxSearch', () => {
        it.each([
            ['', undefined],
            [' ai ', undefined],
            [' api ', 'api'],
            ['checkout crash', 'checkout crash'],
        ])('applies %p as %p', (input, expected) => {
            expect(appliedInboxSearch(input)).toBe(expected)
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
            ['claimed-by-you scope only', { ...DEFAULT_STATE, scope: 'claimed-by-you' }, { scope: 'claimed-by-you' }],
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
                    // `logs` has no entry in the old toolbar list, but the Source filter can offer it.
                    source: 'error_tracking,logs,bogus_source',
                    priority: 'P9,P1',
                    state: 'monitoring,closed,bogus-state',
                    // priority:desc has a valid field and direction but is not one of the offered sort options.
                    sort: 'priority:desc',
                })
            ).toEqual({
                ...DEFAULT_STATE,
                sourceProductFilter: ['error_tracking', 'logs'],
                priorityFilter: ['P1'],
                stateFilter: ['monitoring', 'closed'],
            })
        })

        it.each([
            ['keeps a model sort for a user who can use it', 'ranking_action:desc', true, 'ranking_action', 'desc'],
            [
                'falls back to the default sort for a user who cannot',
                'ranking_action:desc',
                false,
                'recommended',
                'asc',
            ],
            [
                'falls back to the default sort for a head the menu no longer offers',
                'ranking_pr_merged:desc',
                true,
                'recommended',
                'asc',
            ],
            ['keeps an explicit Priority first from a shared link', 'priority:asc', false, 'priority', 'asc'],
            [
                'moves a link with the old Fix sort name to the current one',
                'ranking_fixed:desc',
                true,
                'ranking_fix',
                'desc',
            ],
        ] as const)('%s', (_name, sort, modelSortAvailable, sortField, sortDirection) => {
            expect(parseFilterSearchParams({ sort }, { modelSortAvailable })).toEqual({
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
        it('attributes a Reports query change to the reports tab', async () => {
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

        // The API combines `source_product` and `scout` as AND, so a leftover value from the other
        // dimension would silently narrow the list to reports that match both.
        it.each([
            [{ kind: 'source_product', value: 'logs' }, ['logs'], [], 'logs', undefined],
            [{ kind: 'scout', value: 'my-custom-scout' }, [], ['my-custom-scout'], undefined, 'my-custom-scout'],
            [null, [], [], undefined, undefined],
        ] as const)(
            'replaces the whole source selection with %p and keeps the other filters',
            (selection, sourceProductFilter, scoutFilter, sourceParam, scoutParam) => {
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_SOURCE_FILTER], {
                    [FEATURE_FLAGS.INBOX_SOURCE_FILTER]: true,
                })
                logic.actions.setFilters({
                    ...DEFAULT_STATE,
                    sourceProductFilter: ['error_tracking', 'github'],
                    scoutFilter: ['signals-scout-error-tracking'],
                    priorityFilter: ['P1'],
                    searchQuery: 'checkout',
                })

                logic.actions.setSourceFilter(selection)

                expect(logic.values).toMatchObject({
                    sourceProductFilter,
                    scoutFilter,
                    activeSourceProductFilter: sourceProductFilter,
                    activeScoutFilter: scoutFilter,
                    priorityFilter: ['P1'],
                    searchQuery: 'checkout',
                })
                expect(router.values.searchParams.source).toBe(sourceParam)
                expect(router.values.searchParams.scout).toBe(scoutParam)
                expect(router.values.searchParams.priority).toBe('P1')
            }
        )

        it('ignores a stored source selection while the flag is off and reloads when the flag changes', async () => {
            logic.actions.setFilters({ ...DEFAULT_STATE, scoutFilter: ['my-custom-scout'] })

            expect(logic.values).toMatchObject({
                scoutFilter: ['my-custom-scout'],
                activeScoutFilter: [],
                hasActiveFilters: false,
            })

            await expectLogic(logic, () => {
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_SOURCE_FILTER], {
                    [FEATURE_FLAGS.INBOX_SOURCE_FILTER]: true,
                })
            })
                .toDispatchActions(['sourceFilterAvailabilityChanged'])
                .toMatchValues({ activeScoutFilter: ['my-custom-scout'], hasActiveFilters: true })
        })

        it.each([
            [
                'keeps a stored model sort for staff with the flag',
                'ranking_action',
                true,
                true,
                'ranking_action',
                'ranking_action',
                'desc',
            ],
            // The reset reloads the lists, so rows loaded with the model sort do not stay on screen.
            [
                'resets the stored sort once the flag is off',
                'ranking_action',
                false,
                true,
                'recommended',
                'recommended',
                'asc',
            ],
            [
                'keeps a stored model sort for a non-staff user with the flag',
                'ranking_action',
                true,
                false,
                'ranking_action',
                'ranking_action',
                'desc',
            ],
            [
                'falls back to the default for a stored head the menu no longer offers',
                'ranking_pr_merged',
                true,
                true,
                'ranking_pr_merged',
                'recommended',
                'asc',
            ],
        ] as const)(
            '%s',
            (_name, storedSortField, flagOn, isStaff, sortField, activeSortField, activeSortDirection) => {
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_MODEL_SORT], {
                    [FEATURE_FLAGS.INBOX_MODEL_SORT]: true,
                })
                userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: true })
                // A sort persisted by an older build can name a head the type no longer lists.
                logic.actions.setSort(storedSortField as InboxSortField, 'desc')

                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_MODEL_SORT], {
                    [FEATURE_FLAGS.INBOX_MODEL_SORT]: flagOn,
                })
                userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })

                expect(logic.values).toMatchObject({
                    sortField,
                    activeSortField,
                    activeSortDirection,
                })
            }
        )
    })

    describe('stored sort migration', () => {
        const STORAGE_PREFIX = 'scenes.inbox.logics.inboxFiltersLogic'
        let logic: ReturnType<typeof inboxFiltersLogic.build>

        beforeEach(() => {
            localStorage.clear()
            initKeaTests()
            useMocks({ get: { '/api/projects/:team_id/signals/reports/available_reviewers/': () => [200, {}] } })
        })

        afterEach(() => {
            logic.unmount()
        })

        it.each([
            ['moves the old Priority first default to Recommended', 'priority', 'asc', null, 'recommended', 'asc'],
            ['keeps a Priority first the user picked', 'priority', 'asc', true, 'priority', 'asc'],
            ['keeps Newest first from before Recommended existed', 'created_at', 'desc', null, 'created_at', 'desc'],
        ] as const)('%s', (_name, storedField, storedDirection, chosen, sortField, sortDirection) => {
            localStorage.setItem(`${STORAGE_PREFIX}.sortField`, JSON.stringify(storedField))
            localStorage.setItem(`${STORAGE_PREFIX}.sortDirection`, JSON.stringify(storedDirection))
            if (chosen !== null) {
                localStorage.setItem(`${STORAGE_PREFIX}.hasUserChosenSort`, JSON.stringify(chosen))
            }
            router.actions.push(urls.inbox())

            logic = inboxFiltersLogic()
            logic.mount()

            expect(logic.values).toMatchObject({ sortField, sortDirection })
            expect(router.values.searchParams.sort).toBe(
                sortField === 'recommended' ? undefined : `${sortField}:${sortDirection}`
            )
        })

        it('lets a shared link override the migration', () => {
            localStorage.setItem(`${STORAGE_PREFIX}.sortField`, JSON.stringify('priority'))
            localStorage.setItem(`${STORAGE_PREFIX}.sortDirection`, JSON.stringify('asc'))
            router.actions.push(urls.inbox(), { sort: 'created_at:desc' })

            logic = inboxFiltersLogic()
            logic.mount()

            expect(logic.values).toMatchObject({ sortField: 'created_at', sortDirection: 'desc' })
        })
    })
})
