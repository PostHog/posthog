import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType, StartupProgramLabel } from '~/types'

import { legalDocumentsLogic } from './legalDocumentsLogic'

function billingWithBoost(startupProgramLabel: StartupProgramLabel | null): BillingType {
    return {
        startup_program_label: startupProgramLabel,
        products: [{ type: 'platform_and_support', addons: [{ type: 'boost', subscribed: true }] }],
    } as unknown as BillingType
}

describe('legalDocumentsLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/legal_documents/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        billingLogic.mount()
    })

    it.each([
        ['Startup', StartupProgramLabel.Startup, false, 'startup_program'],
        ['Startup with the override flag', StartupProgramLabel.Startup, true, null],
        ['YC', StartupProgramLabel.YC, false, null],
        ['no program', null, false, null],
    ])('resolves baaBlockReason for a %s org', async (_name, label, overrideEnabled, expected) => {
        featureFlagLogic.actions.setFeatureFlags(
            overrideEnabled ? [FEATURE_FLAGS.LEGAL_DOCUMENTS_BAA_STARTUP_OVERRIDE] : [],
            overrideEnabled ? { [FEATURE_FLAGS.LEGAL_DOCUMENTS_BAA_STARTUP_OVERRIDE]: true } : {}
        )
        billingLogic.actions.loadBillingSuccess(billingWithBoost(label))
        const logic = legalDocumentsLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ baaBlockReason: expected })
        expect(logic.values.baaBlockReason).toBe(expected)
    })
})
