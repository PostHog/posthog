import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { defaultPlatformAddons } from '~/mocks/fixtures/_billing_platform_addons'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingPlan, BillingType, StartupProgramLabel } from '~/types'

import { legalDocumentsLogic } from './legalDocumentsLogic'

function billingFor(startupProgramLabel: StartupProgramLabel | null, boostSubscribed: boolean): BillingType {
    return {
        ...billingJson,
        startup_program_label: startupProgramLabel,
        products: billingJson.products.map((product) =>
            product.type === 'platform_and_support'
                ? {
                      ...product,
                      addons: defaultPlatformAddons.map((addon) => ({
                          ...addon,
                          subscribed: boostSubscribed && addon.type === BillingPlan.Boost,
                      })),
                  }
                : product
        ),
    }
}

describe('legalDocumentsLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/legal_documents/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        userLogic.mount()
        billingLogic.mount()
    })

    it.each([
        ['Startup', StartupProgramLabel.Startup, true, false, 'startup_program'],
        ['Startup while impersonated', StartupProgramLabel.Startup, true, true, null],
        ['Startup while impersonated but no add-on', StartupProgramLabel.Startup, false, true, 'no_qualifying_addon'],
        ['YC', StartupProgramLabel.YC, true, false, null],
        ['no program', null, true, false, null],
        ['no program without an add-on', null, false, false, 'no_qualifying_addon'],
    ])('resolves baaBlockReason for a %s org', async (_name, label, boostSubscribed, impersonated, expected) => {
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_impersonated: impersonated })
        billingLogic.actions.loadBillingSuccess(billingFor(label, boostSubscribed))
        const logic = legalDocumentsLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ baaBlockReason: expected })
        expect(logic.values.baaBlockReason).toBe(expected)
    })
})
