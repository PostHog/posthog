/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_FOR_YOU,
    InboxFlatListTabKey,
    InboxScope,
    SignalReport,
} from '../types'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic, shouldDefaultToEntireProject } from './reportListLogic'

const REPORT = (id: string): SignalReport => ({ id, status: 'ready' }) as unknown as SignalReport

describe('reportListLogic', () => {
    describe('shouldDefaultToEntireProject', () => {
        const base = {
            tabKey: 'pulls' as InboxFlatListTabKey,
            scope: INBOX_SCOPE_FOR_YOU as InboxScope,
            hasUserChosenScope: false,
            hasResolvedUser: true,
            count: 0 as number | null,
        }

        it('switches to Entire project when a fresh user has zero assigned PRs', () => {
            expect(shouldDefaultToEntireProject(base)).toBe(true)
        })

        it.each<[string, Partial<typeof base>]>([
            // The user has PRs assigned – keep them on For you.
            ['user has assigned PRs', { count: 3 }],
            // The user deliberately picked a scope – never override it, even with zero PRs.
            ['user chose their scope', { hasUserChosenScope: true }],
            // Only the Pull requests tab (their assigned PRs) drives the default.
            ['not the pulls tab', { tabKey: 'reports' as InboxFlatListTabKey }],
            // Already off For you – nothing to default.
            ['already entire project', { scope: INBOX_SCOPE_ENTIRE_PROJECT as InboxScope }],
            // Count for For-you scope is only meaningful once the user's uuid has resolved.
            ['user not resolved yet', { hasResolvedUser: false }],
            // Count request in flight / failed (null) is not treated as "zero".
            ['count not loaded', { count: null }],
        ])('stays put when %s', (_label, override) => {
            expect(shouldDefaultToEntireProject({ ...base, ...override })).toBe(false)
        })
    })

    describe('list loading', () => {
        let logic: ReturnType<typeof reportListLogic.build>
        // The list endpoint serves both the badge count (limit=1) and the page load; a flag lets a
        // single test make only the page load fail while the count still succeeds.
        let failPageLoad = false

        const mountPullsTab = (): void => {
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/': ({ request }) => {
                        if (new URL(request.url).searchParams.get('limit') === '1') {
                            return [200, { count: 3, results: [], next: null, previous: null }]
                        }
                        if (failPageLoad) {
                            return [500, { detail: 'boom' }]
                        }
                        return [200, { count: 2, results: [REPORT('a'), REPORT('b')], next: null, previous: null }]
                    },
                },
            })
            logic = reportListLogic({ tabKey: 'pulls', listParams: INBOX_FLAT_TAB_LIST_PARAMS.pulls })
            logic.mount()
        }

        beforeEach(() => {
            failPageLoad = false
            initKeaTests()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('retries a list that never loaded when the scope changes', async () => {
            failPageLoad = true
            mountPullsTab()
            logic.actions.ensureLoaded()
            await expectLogic(logic).toDispatchActions(['loadReportsFailure']).toFinishAllListeners()
            expect(logic.values.reportsLoadFailed).toBe(true)
            expect(logic.values.isLoaded).toBe(false)

            // The page load now succeeds. Changing scope must reload the failed list, not only the
            // badge count — the regression is `refresh` skipping the list whenever `isLoaded` is false.
            failPageLoad = false
            logic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)
            await expectLogic(logic).toDispatchActions(['loadReportsSuccess']).toFinishAllListeners()
            expect(logic.values.isLoaded).toBe(true)
            expect(logic.values.reports).toHaveLength(2)
        })

        it('prefers the loaded total over the standalone count for the badge', async () => {
            mountPullsTab()
            logic.actions.ensureLoaded()
            await expectLogic(logic).toDispatchActions(['loadReportsSuccess']).toFinishAllListeners()
            // The count request reports 3, the page load reports 2. Once the list is loaded the badge
            // must follow the loaded total, so it can never disagree with the rows the body shows.
            expect(logic.values.count).toBe(3)
            expect(logic.values.totalCount).toBe(2)
            expect(logic.values.badgeCount).toBe(2)
        })
    })
})
