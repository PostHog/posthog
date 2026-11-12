import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowEmailSendingRateLimitApi } from 'products/workflows/frontend/generated/api.schemas'

import { broadcastSendingLogic } from './broadcastSendingLogic'
import { broadcastWizardLogic, remainingSendDuration } from './broadcastWizardLogic'

const LIVE_BROADCAST = {
    id: 'broadcast-1',
    name: 'Product update',
    status: 'active',
    origin_product: 'broadcasts',
    trigger: { type: 'batch', filters: { properties: [] } },
    actions: [],
    edges: [],
    schedules: [],
    user_access_level: 'editor',
    email_sending_rate_limit: { count: 100, period: 'minute' },
    email_sending_paused_at: null,
}

describe('broadcastSendingLogic', () => {
    it.each([
        { remaining: 6000, limit: { count: 100, period: 'minute' }, expected: '1h' },
        { remaining: 500, limit: { count: 1000, period: 'hour' }, expected: '30m' },
        { remaining: 0, limit: { count: 100, period: 'minute' }, expected: '' },
        { remaining: 500, limit: null, expected: '' },
    ])('estimates %o as the time left', ({ remaining, limit, expected }) => {
        expect(remainingSendDuration(remaining, limit as HogFlowEmailSendingRateLimitApi | null)).toBe(expected)
    })

    it.each([
        { change: 'a new limit', draft: { count: 20, period: 'hour' } },
        { change: 'no limit', draft: null },
    ])('saves $change to the live broadcast', async ({ draft }) => {
        const patches: unknown[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/:id/': () => [200, LIVE_BROADCAST],
                '/api/projects/:team_id/hog_flows/:id/in_flight/': () => [
                    200,
                    { count: 0, by_action: {}, position_unknown: 0 },
                ],
            },
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    patches.push(await request.json())
                    return [200, LIVE_BROADCAST]
                },
            },
        })
        initKeaTests()
        const wizard = broadcastWizardLogic({ id: 'broadcast-1' })
        wizard.mount()
        const logic = broadcastSendingLogic({ id: 'broadcast-1' })
        logic.mount()
        await expectLogic(wizard).toDispatchActions(['loadBroadcastSuccess'])

        logic.actions.openSendingRateModal()
        expect(logic.values.sendingRateDraft).toEqual({ count: 100, period: 'minute' })
        logic.actions.setSendingRateDraft(draft as HogFlowEmailSendingRateLimitApi | null)
        logic.actions.saveSendingRate()
        await expectLogic(logic).toDispatchActions(['closeSendingRateModal']).toFinishAllListeners()

        expect(patches).toEqual([{ email_sending_rate_limit: draft }])
        expect(wizard.values.emailRateLimit).toEqual(draft)
        expect(logic.values.sendingRateModalOpen).toBe(false)
    })
})
