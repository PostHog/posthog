import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { personalCodexIntegrationLogic } from 'scenes/settings/user/personalCodexIntegrationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ModelAccessEnumApi, RuntimeAdapterEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { codexBillingLogic, codexModelAccessForRun } from './codexBillingLogic'

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
                await expect(codexModelAccessForRun(adapter)).resolves.toBe(expected)
                logic.mount()
            }
        )
    })
})
