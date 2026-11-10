import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'lib/logic/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, BillingType, StartupProgramLabel } from '~/types'

import { legalDocumentsLogic } from './legalDocumentsLogic'

function billingFor(startupProgramLabel: StartupProgramLabel | null, onBoostTrial: boolean): BillingType {
    return {
        ...billingJson,
        startup_program_label: startupProgramLabel,
        trial: onBoostTrial ? { type: 'autosubscribe', status: 'active', target: 'boost', expires_at: '' } : undefined,
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
        ['Startup', StartupProgramLabel.Startup, true, false, false, 'startup_program'],
        ['Startup while impersonated', StartupProgramLabel.Startup, true, false, true, null],
        [
            'Startup while impersonated but not entitled',
            StartupProgramLabel.Startup,
            false,
            false,
            true,
            'no_qualifying_addon',
        ],
        ['YC', StartupProgramLabel.YC, true, false, false, null],
        ['no program', null, true, false, false, null],
        ['no program without the entitlement', null, false, false, false, 'no_qualifying_addon'],
        ['add-on trial', null, true, true, false, 'no_qualifying_addon'],
    ])('resolves baaBlockReason for a %s org', async (_name, label, entitled, onBoostTrial, impersonated, expected) => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            is_impersonated: impersonated,
            organization: {
                ...MOCK_DEFAULT_USER.organization!,
                available_product_features: entitled ? [{ key: AvailableFeature.HIPAA_BAA, name: 'HIPAA BAA' }] : [],
            },
        })
        billingLogic.actions.loadBillingSuccess(billingFor(label, onBoostTrial))
        const logic = legalDocumentsLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ baaBlockReason: expected })
        expect(logic.values.baaBlockReason).toBe(expected)
    })
})
