import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import { groupsFindRetrieve } from '../generated/api'
import { groupLogic, resolveBackNavigation } from './groupLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    groupsFindRetrieve: jest.fn(),
}))

const mockGroupsFindRetrieve = groupsFindRetrieve as jest.MockedFunction<typeof groupsFindRetrieve>

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

    describe('loadGroup failure', () => {
        beforeEach(() => {
            initKeaTests()
            jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
            jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)
            jest.spyOn(api, 'query').mockResolvedValue({ results: [] } as any)
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it.each([
            { status: 404, reported: false },
            { status: 500, reported: true },
        ])('toasts and reports a $status from the group lookup: $reported', async ({ status, reported }) => {
            const error = new ApiError('Request failed', status, undefined, { detail: 'Request failed' })
            mockGroupsFindRetrieve.mockRejectedValueOnce(error)

            const logic = groupLogic({ groupTypeIndex: 0, groupKey: 'missing-group' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadGroupFailure'])

            expect(logic.values.groupData).toBeNull()
            expect(lemonToast.error).toHaveBeenCalledTimes(reported ? 1 : 0)
            expect(posthog.captureException).toHaveBeenCalledTimes(reported ? 1 : 0)
        })
    })
})
