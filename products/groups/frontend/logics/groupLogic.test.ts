import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { groupLogic, resolveBackNavigation } from './groupLogic'

describe('groupLogic', () => {
    describe('resolveBackNavigation', () => {
        it('returns the sanitized internal path and name', () => {
            expect(resolveBackNavigation({ backUrl: '/customer_analytics/accounts', backName: 'Accounts' })).toEqual({
                url: '/customer_analytics/accounts',
                name: 'Accounts',
            })
        })

        it('preserves search and hash on the internal path', () => {
            expect(
                resolveBackNavigation({
                    backUrl: '/customer_analytics/accounts?tab=usage#view=abc',
                    backName: 'Accounts',
                })
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
            expect(resolveBackNavigation({ backUrl: '/groups/0/acme' })).toEqual({
                url: '/groups/0/acme',
                name: 'Back',
            })
        })
    })

    describe('loadGroupRevenueAnalyticsData', () => {
        let logic: ReturnType<typeof groupLogic.build>
        let querySpy: jest.SpyInstance

        beforeEach(() => {
            initKeaTests()
            window.POSTHOG_APP_CONTEXT = { current_team: { id: 123 } } as AppContext
            const emptyResponse: HogQLQueryResponse = { results: [] }
            querySpy = jest.spyOn(api, 'query').mockResolvedValue(emptyResponse)
        })

        afterEach(() => {
            logic?.unmount()
            querySpy.mockRestore()
        })

        it('skips the query when the group key is empty', async () => {
            logic = groupLogic({ groupTypeIndex: 0, groupKey: '' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(querySpy).not.toHaveBeenCalled()
            expect(logic.values.groupRevenueAnalyticsData).toBeNull()
        })

        it('queries revenue analytics when the group key is present', async () => {
            logic = groupLogic({ groupTypeIndex: 0, groupKey: 'acme' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(querySpy).toHaveBeenCalledWith(expect.objectContaining({ values: { groupKey: 'acme' } }))
        })
    })
})
