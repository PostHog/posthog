import { ApiError } from 'lib/api-error'
import * as takeOwnership from 'lib/components/openTakeOwnershipDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import * as generatedApi from 'products/subscriptions/frontend/generated/api'

import { toggleSubscriptionEnabled } from './toggleSubscriptionEnabled'

jest.mock('lib/utils/getAppContext', () => ({
    getCurrentTeamId: () => 1,
}))

describe('toggleSubscriptionEnabled', () => {
    let patchSpy: jest.SpyInstance
    let successSpy: jest.SpyInstance
    let errorSpy: jest.SpyInstance

    beforeEach(() => {
        patchSpy = jest.spyOn(generatedApi, 'subscriptionsPartialUpdate')
        successSpy = jest.spyOn(lemonToast, 'success').mockImplementation(jest.fn())
        errorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('returns true and surfaces an enabled toast on success', async () => {
        patchSpy.mockResolvedValueOnce({ id: 42, enabled: true } as any)

        const ok = await toggleSubscriptionEnabled(42, true)

        expect(ok).toBe(true)
        expect(patchSpy).toHaveBeenCalledWith('1', 42, { enabled: true })
        expect(successSpy).toHaveBeenCalledWith('Subscription enabled')
        expect(errorSpy).not.toHaveBeenCalled()
    })

    it('returns true and surfaces a disabled toast on success', async () => {
        patchSpy.mockResolvedValueOnce({ id: 42, enabled: false } as any)

        const ok = await toggleSubscriptionEnabled(42, false)

        expect(ok).toBe(true)
        expect(successSpy).toHaveBeenCalledWith('Subscription disabled')
    })

    it('returns false and surfaces the API detail on error', async () => {
        patchSpy.mockRejectedValueOnce({ detail: 'Slack integration disconnected' })

        const ok = await toggleSubscriptionEnabled(42, true)

        expect(ok).toBe(false)
        expect(errorSpy).toHaveBeenCalledWith('Slack integration disconnected')
        expect(successSpy).not.toHaveBeenCalled()
    })

    it('returns false and uses the fallback toast when error has no detail', async () => {
        patchSpy.mockRejectedValueOnce(new Error('network down'))

        const ok = await toggleSubscriptionEnabled(42, true)

        expect(ok).toBe(false)
        expect(errorSpy).toHaveBeenCalledWith('Could not update subscription')
    })

    it('offers to take ownership instead of toasting when the owner can no longer run it', async () => {
        patchSpy.mockRejectedValueOnce(new ApiError('refused', 400, undefined, { code: 'owner_unavailable' }))
        const takeSpy = jest.spyOn(generatedApi, 'subscriptionsTakeOwnershipCreate').mockResolvedValueOnce({} as any)
        const dialogSpy = jest
            .spyOn(takeOwnership, 'openTakeOwnershipDialog')
            .mockImplementation(async ({ takeOwnership: take }) => {
                await take()
                return true
            })

        const ok = await toggleSubscriptionEnabled(42, true)

        expect(ok).toBe(true)
        expect(dialogSpy).toHaveBeenCalledWith(
            expect.objectContaining({ resourceLabel: 'subscription', resourceId: 42 })
        )
        expect(takeSpy).toHaveBeenCalledWith('1', '42')
        expect(errorSpy).not.toHaveBeenCalled()
    })

    it('treats non-string detail as missing and uses the fallback toast', async () => {
        // Defends against API drift where `detail` becomes an object/array/null.
        patchSpy.mockRejectedValueOnce({ detail: { enabled: ['Schedule has reached its end date.'] } })

        const ok = await toggleSubscriptionEnabled(42, true)

        expect(ok).toBe(false)
        expect(errorSpy).toHaveBeenCalledWith('Could not update subscription')
    })
})
