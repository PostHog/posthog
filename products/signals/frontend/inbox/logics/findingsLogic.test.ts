/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { findingsLogic } from './findingsLogic'

describe('findingsLogic', () => {
    let logic: ReturnType<typeof findingsLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/scout/configs/': () => [200, []],
                '/api/projects/:team_id/signals/scout/runs/': () => [200, []],
                '/api/projects/:team_id/signals/scout/runs/recent-per-scout/': () => [200, []],
            },
        })
        initKeaTests()
        router.actions.push(urls.inboxFindings())
        logic = findingsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    // The filters were in-memory state, so a refresh or a shared link opened the unfiltered list.
    // The params are prefixed because `inboxFiltersLogic` owns the bare `scout`, `sort`, and
    // `search` keys on this route and deletes them on every rewrite.
    it('writes the non-default filters to the URL and keeps the bare view clean', async () => {
        logic.actions.setScoutFilter('signals-scout-errors')
        logic.actions.setSeverityFilter('P1')
        logic.actions.setSortKey('oldest')
        logic.actions.setSearchText('checkout')
        // The search waits for its pause, so typing does not rewrite the URL per keystroke.
        expect(router.values.searchParams.finding_search).toBeUndefined()
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toMatchObject({
            finding_scout: 'signals-scout-errors',
            finding_severity: 'P1',
            finding_sort: 'oldest',
            finding_search: 'checkout',
        })

        logic.actions.setScoutFilter('all')
        logic.actions.setSeverityFilter('all')
        logic.actions.setSortKey('newest')
        logic.actions.setSearchText('')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams.finding_scout).toBeUndefined()
        expect(router.values.searchParams.finding_severity).toBeUndefined()
        expect(router.values.searchParams.finding_sort).toBeUndefined()
        expect(router.values.searchParams.finding_search).toBeUndefined()
    })

    it('restores the filters from a shared URL', async () => {
        router.actions.push(urls.inboxFindings(), {
            finding_search: 'checkout',
            finding_scout: 'signals-scout-errors',
            finding_severity: 'P1',
            finding_sort: 'severity',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.searchText).toEqual('checkout')
        expect(logic.values.scoutFilter).toEqual('signals-scout-errors')
        expect(logic.values.severityFilter).toEqual('P1')
        expect(logic.values.sortKey).toEqual('severity')
    })

    // A hand-edited or outdated link must open the panel, not a list filtered by junk.
    it('falls back to the defaults for values it cannot read', async () => {
        router.actions.push(urls.inboxFindings(), {
            finding_severity: 'P9',
            finding_sort: 'loudest',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.severityFilter).toEqual('all')
        expect(logic.values.sortKey).toEqual('newest')
    })

    // kea-router hands back a number for `?finding_search=123`, and a string-only read would drop
    // a search a person can type.
    it('restores a search the router parsed as a number', async () => {
        router.actions.push(`${urls.inboxFindings()}?finding_search=123`)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.searchText).toEqual('123')
    })

    // The URL only ever carries a trimmed search, so hydrating it back over a half-typed `error `
    // would strip the trailing space the person is still using and join their next word onto it.
    it('leaves a half-typed search alone when the URL already carries its trimmed form', async () => {
        logic.actions.setSearchText('error ')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams.finding_search).toEqual('error')
        expect(logic.values.searchText).toEqual('error ')
    })

    it('reflects the filters it already holds onto a bare findings URL', async () => {
        logic.actions.setSeverityFilter('P0')
        await expectLogic(logic).toFinishAllListeners()

        router.actions.push(urls.inboxFindings())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.severityFilter).toEqual('P0')
        expect(router.values.searchParams.finding_severity).toEqual('P0')
    })
})
