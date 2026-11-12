import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
        expect(logic.values.todayPeopleRecent).toBeNull()

        logic.actions.loadGroupSuccess({
            group_type_index: 0,
            group_key: 'acme',
            group_properties: { name: 'Acme Inc' },
            created_at: '2026-01-01T00:00:00Z',
            notebook: null,
        })

        expect(logic.values.todayPeopleRecent).toEqual({
            type: 'group',
            name: 'Acme Inc',
            href: urls.group('0', 'acme'),
        })
    })
})
