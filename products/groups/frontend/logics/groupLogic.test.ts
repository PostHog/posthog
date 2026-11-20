import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { groupLogic, resolveBackNavigation } from './groupLogic'

describe('resolveBackNavigation', () => {
    it('returns the sanitized internal path and name', () => {
        expect(resolveBackNavigation({ backUrl: '/customer_analytics/accounts', backName: 'Accounts' })).toEqual({
            url: '/customer_analytics/accounts',
            name: 'Accounts',
        })
    })

    it('preserves search and hash on the internal path', () => {
        expect(
            resolveBackNavigation({ backUrl: '/customer_analytics/accounts?tab=usage#view=abc', backName: 'Accounts' })
        ).toEqual({ url: '/customer_analytics/accounts?tab=usage#view=abc', name: 'Accounts' })
    })

    it('rejects an absolute external URL (open redirect guard)', () => {
        expect(resolveBackNavigation({ backUrl: 'https://evil.com', backName: 'Accounts' })).toBeNull()
    })

    it('rejects a protocol-relative URL', () => {
        expect(resolveBackNavigation({ backUrl: '//evil.com' })).toBeNull()
    })

    it('returns null when backUrl is absent', () => {
        expect(resolveBackNavigation({})).toBeNull()
    })

    it('falls back to a default name when backName is missing', () => {
        expect(resolveBackNavigation({ backUrl: '/groups/0/acme' })).toEqual({ url: '/groups/0/acme', name: 'Back' })
    })
})

describe('groupLogic todayPeopleRecent', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/groups/find/': { status: 404 } } })
        initKeaTests()
    })

    it('gives the loaded group as a People recent', () => {
        const logic = groupLogic({ groupTypeIndex: 0, groupKey: 'acme' })
        logic.mount()
        expect(logic.values.todayRecent).toBeNull()

        logic.actions.loadGroupSuccess({
            group_type_index: 0,
            group_key: 'acme',
            group_properties: { name: 'Acme Inc' },
            created_at: '2026-01-01T00:00:00Z',
            notebook: null,
        })

        expect(logic.values.todayRecent).toEqual({
            type: 'group',
            name: 'Acme Inc',
            href: urls.group('0', 'acme'),
        })
    })
})

describe('groupLogic flag calls', () => {
    let logic: ReturnType<typeof groupLogic.build>

    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/groups/find/': { status: 404 } } })
        initKeaTests()
        logic = groupLogic({ groupTypeIndex: 1, groupKey: 'acme' })
        logic.mount()
    })

    it.each([
        ['flag evaluations mode 2 or the native JSON events table', true],
        ['mode 0 and the legacy events table', false],
    ])('for a team on %s, showFlagCallsTab is %s', (_, onlyInFlagEvaluations) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            flag_calls_only_in_flag_evaluations: onlyInFlagEvaluations,
        })

        expect(logic.values.showFlagCallsTab).toBe(onlyInFlagEvaluations)
    })

    it('lists only the group flag calls from the last 24 hours', () => {
        const query = logic.values.groupFlagCallsQuery!
        expect(query).toMatchObject({
            showEventFilter: false,
            showEventsFilter: false,
            showTableViews: false,
            showSavedQueries: false,
            showSavedFilters: false,
        })
        expect(query.source).toMatchObject({
            kind: NodeKind.EventsQuery,
            event: '$feature_flag_called',
            after: '-24h',
            fixedProperties: [
                {
                    key: '$group_1',
                    value: 'acme',
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.Exact,
                },
            ],
        })
        expect((query.source as any).events).toBeUndefined()
    })

    it.each([
        ['-24h', false],
        ['-180d', true],
    ])('with the range starting at %s, groupFlagCallsReachPastRetention is %s', (after, expected) => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_calls_only_in_flag_evaluations: true })
        const current = logic.values.groupFlagCallsQuery!
        logic.actions.setGroupFlagCallsQuery({ ...current, source: { ...current.source, after } as any })

        expect(logic.values.groupFlagCallsReachPastRetention).toBe(expected)
    })
})
