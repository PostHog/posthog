import { expectLogic } from 'kea-test-utils'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { BillingType } from '~/types'

import type { EmailSendingAllowanceApi } from 'products/workflows/frontend/generated/api.schemas'

import { workflowsReputationLogic } from './workflowsReputationLogic'

const allowance: EmailSendingAllowanceApi = {
    tier: 2,
    max_tier: 4,
    emails_per_hour: 5000,
    emails_per_day: 50000,
    max_batch_audience: 25000,
    emails_sent_last_hour: 1200,
    emails_sent_last_day: 18400,
    enforced: true,
}

describe('workflowsReputationLogic', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/reputation': { workflows: [], isps: [] } } })
        initKeaTests()
    })

    it.each([
        ['shows the request on a paid plan with the flag on', true, true],
        ['hides the request when the flag is off', false, false],
    ])('%s', async (_name, flagOn, expected) => {
        const logic = workflowsReputationLogic()
        logic.mount()
        billingLogic.actions.loadBillingSuccess({ subscription_level: 'paid' } as BillingType)
        const flag = FEATURE_FLAGS.WORKFLOWS_SENDING_TIER_REQUESTS
        featureFlagLogic.actions.setFeatureFlags(flagOn ? [flag] : [], { [flag]: flagOn })

        expect(logic.values.canRequestSendingTierIncrease).toBe(expected)
    })

    it('opens the support composer with the tier request details attached', async () => {
        const logic = workflowsReputationLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.requestSendingTierIncrease(allowance)).toFinishAllListeners()

        expect(supportLogic.values.isEmailFormOpen).toBe(true)
        expect(supportLogic.values.sendSupportRequest).toMatchObject({ kind: 'support' })
        const context = supportLogic.values.sendSupportRequest.ticket_context ?? ''
        expect(context.split('\n')[0]).toBe('Email sending tier increase request')
        expect(context).toContain('Current tier: 2 of 4')
    })
})
