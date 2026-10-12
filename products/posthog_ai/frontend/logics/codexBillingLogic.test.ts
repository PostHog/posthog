import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { personalCodexIntegrationLogic } from 'scenes/settings/user/personalCodexIntegrationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ModelAccessEnumApi, RuntimeAdapterEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import {
    CodexBillingUnresolvedError,
    codexBillingLogic,
    codexModelAccessForRun,
    pickedCodexModelAccess,
} from './codexBillingLogic'

const AUTH_FILE = JSON.stringify({
    tokens: { access_token: 'fake-access', refresh_token: 'fake-refresh', id_token: 'fake-id' },
})

describe('codexBillingLogic', () => {
    let logic: ReturnType<typeof codexBillingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: { '/api/users/@me/integrations/codex/': { status: 'not_connected' } },
            post: {
                '/api/users/@me/integrations/codex/': { status: 'connected', email: 'jane@example.com' },
            },
        })
        initKeaTests()
        logic = codexBillingLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['from the billing row', true, ModelAccessEnumApi.OwnSubscription],
        ['from settings', false, ModelAccessEnumApi.PosthogGateway],
    ])('picks the billing after a connect started %s', async (_name, fromBillingRow, expected) => {
        await expectLogic(logic).toFinishAllListeners()

        if (fromBillingRow) {
            logic.actions.connectPlan('composer:test')
        } else {
            personalCodexIntegrationLogic.actions.openConnectModal('settings')
        }
        personalCodexIntegrationLogic.actions.pasteAuthFile(AUTH_FILE)

        await expectLogic(logic).toDispatchActions(['connectCodexSuccess']).toFinishAllListeners()

        expect(logic.values.planConnected).toBe(true)
        expect(logic.values.effectiveCodexModelAccess).toBe(expected)
    })

    describe('codexModelAccessForRun', () => {
        const FLAG = FEATURE_FLAGS.POSTHOG_CODE_CODEX_OWN_SUBSCRIPTION_CLOUD

        it.each([
            ['the flag is off', false, RuntimeAdapterEnumApi.Codex, 'connected', null],
            [
                'the run is on Claude',
                true,
                RuntimeAdapterEnumApi.Claude,
                'connected',
                ModelAccessEnumApi.PosthogGateway,
            ],
            [
                'the account is connected',
                true,
                RuntimeAdapterEnumApi.Codex,
                'connected',
                ModelAccessEnumApi.OwnSubscription,
            ],
            [
                'the account was disconnected',
                true,
                RuntimeAdapterEnumApi.Codex,
                'not_connected',
                ModelAccessEnumApi.PosthogGateway,
            ],
        ])(
            'with the plan saved, when %s, resolves before the picker mounts',
            async (_name, flagOn, adapter, status, expected) => {
                logic.actions.setPreferredCodexModelAccess(ModelAccessEnumApi.OwnSubscription)
                logic.unmount()
                featureFlagLogic.actions.setFeatureFlags(flagOn ? [FLAG] : [], flagOn ? { [FLAG]: true } : {})
                useMocks({ get: { '/api/users/@me/integrations/codex/': { status } } })

                expect(codexBillingLogic.findMounted()).toBeNull()
                await expect(codexModelAccessForRun(async () => adapter)).resolves.toBe(expected)
                logic.mount()
            }
        )

        it.each([
            ['the harness is unknown', null, [200, { status: 'connected' }]],
            ['the connection lookup fails', RuntimeAdapterEnumApi.Codex, [500, {}]],
        ])('with the plan saved, when %s, refuses to pick a billing', async (_name, adapter, response) => {
            logic.actions.setPreferredCodexModelAccess(ModelAccessEnumApi.OwnSubscription)
            logic.unmount()
            featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: true })
            useMocks({ get: { '/api/users/@me/integrations/codex/': () => response } })

            await expect(codexModelAccessForRun(async () => adapter)).rejects.toBeInstanceOf(
                CodexBillingUnresolvedError
            )
            logic.mount()
        })
    })

    it('leaves a resume billing off while the connection loads with the plan saved', async () => {
        const FLAG = FEATURE_FLAGS.POSTHOG_CODE_CODEX_OWN_SUBSCRIPTION_CLOUD
        logic.actions.setPreferredCodexModelAccess(ModelAccessEnumApi.OwnSubscription)
        logic.unmount()
        featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: true })
        let finishLoad!: () => void
        const loaded = new Promise<void>((resolve) => {
            finishLoad = resolve
        })
        useMocks({
            get: {
                '/api/users/@me/integrations/codex/': async () => {
                    await loaded
                    return [200, { status: 'connected' }]
                },
            },
        })
        logic = codexBillingLogic()
        logic.mount()
        expect(codexBillingLogic.findMounted()).not.toBeNull()

        expect(pickedCodexModelAccess(RuntimeAdapterEnumApi.Codex)).toBeNull()
        expect(pickedCodexModelAccess(RuntimeAdapterEnumApi.Claude)).toBe(ModelAccessEnumApi.PosthogGateway)

        finishLoad()
        await waitFor(() =>
            expect(pickedCodexModelAccess(RuntimeAdapterEnumApi.Codex)).toBe(ModelAccessEnumApi.OwnSubscription)
        )
    })
})
