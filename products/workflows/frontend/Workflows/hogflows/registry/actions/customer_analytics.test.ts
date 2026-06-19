import './customer_analytics'

import { FEATURE_FLAGS } from 'lib/constants'

import { getRegisteredActionNodeCategories } from './actionNodeRegistry'

describe('customer analytics action registry', () => {
    const getCategory = (): ReturnType<typeof getRegisteredActionNodeCategories>[number] => {
        const category = getRegisteredActionNodeCategories().find((c) => c.label === 'Customer analytics')
        if (!category) {
            throw new Error('Customer analytics action category not registered')
        }
        return category
    }

    it('gates the category behind the customer analytics CSP feature flag', () => {
        expect(getCategory().featureFlag).toBe(FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP)
    })

    it('wires the Get account node to its hog function template', () => {
        const node = getCategory().nodes.find((n) => n.name === 'Get account')
        expect(node).toMatchObject({
            type: 'function',
            config: { template_id: 'template-posthog-get-account' },
        })
    })

    it('flattens the requested account fields into prefixed variables', () => {
        const node = getCategory().nodes.find((n) => n.name === 'Get account')
        const outputVars = node?.output_variable
        if (!Array.isArray(outputVars)) {
            throw new Error('Get account output_variable should be an array of field mappings')
        }

        expect(outputVars).toContainEqual({ key: 'account', result_path: null, label: 'Account' })
        expect(outputVars).toContainEqual({
            key: 'account_csm_email',
            result_path: 'properties.csm.email',
            label: 'CSM email',
        })
        expect(outputVars).toContainEqual({
            key: 'account_executive_id',
            result_path: 'properties.account_executive.id',
            label: 'Account executive ID',
        })
        expect(outputVars).toContainEqual({
            key: 'account_slack_channel_id',
            result_path: 'properties.slack_channel_id',
            label: 'Slack channel ID',
        })

        expect(outputVars.map((v) => v.key)).toEqual([
            'account',
            'account_csm_email',
            'account_csm_id',
            'account_executive_email',
            'account_executive_id',
            'account_owner_email',
            'account_owner_id',
            'account_stripe_customer_id',
            'account_hubspot_deal_id',
            'account_billing_id',
            'account_sfdc_id',
            'account_zendesk_id',
            'account_slack_channel_id',
        ])
    })

    it('wires the Update account node to its hog function template', () => {
        const node = getCategory().nodes.find((n) => n.name === 'Update account')
        expect(node).toMatchObject({
            type: 'function',
            config: { template_id: 'template-posthog-update-account' },
        })
    })
})
