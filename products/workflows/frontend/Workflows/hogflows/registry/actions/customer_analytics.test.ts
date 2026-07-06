import { FEATURE_FLAGS } from 'lib/constants'

import { GroupType, GroupTypeIndex } from '~/types'

import { getRegisteredActionNodeCategories } from './actionNodeRegistry'
import { buildAccountExternalIdInputs } from './customer_analytics'

const groupTypesMap = (...entries: [GroupTypeIndex, string][]): Map<GroupTypeIndex, GroupType> =>
    new Map(entries.map(([index, groupType]) => [index, { group_type: groupType, group_type_index: index }]))

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

    it.each(['Get account', 'Update account'])('gives %s a dynamic external_id default resolver', (name) => {
        const node = getCategory().nodes.find((n) => n.name === name)
        expect(typeof node?.getDefaultInputs).toBe('function')
    })

    describe('buildAccountExternalIdInputs', () => {
        it('builds a name-based group key expression from the account group type index', () => {
            const inputs = buildAccountExternalIdInputs(2, groupTypesMap([0, 'project'], [2, 'organization']))
            expect(inputs).toEqual({ external_id: { value: '{groups.`organization`.id}' } })
        })

        it('backtick-quotes the group type so a name with template delimiters is escaped, not injected', () => {
            const malicious = '"].id} + inject {groups["x'
            const inputs = buildAccountExternalIdInputs(0, groupTypesMap([0, malicious]))
            expect(inputs).toEqual({ external_id: { value: '{groups.`"].id} + inject {groups["x`.id}' } })
        })

        it('escapes backticks in the group type by doubling them', () => {
            const inputs = buildAccountExternalIdInputs(0, groupTypesMap([0, 'we`ird']))
            expect(inputs).toEqual({ external_id: { value: '{groups.`we``ird`.id}' } })
        })

        it.each([null, undefined])('returns undefined when the account group type index is %s', (index) => {
            expect(buildAccountExternalIdInputs(index, groupTypesMap([0, 'organization']))).toBeUndefined()
        })

        it('returns undefined when the configured index has no matching group type', () => {
            expect(buildAccountExternalIdInputs(3, groupTypesMap([0, 'organization']))).toBeUndefined()
        })
    })
})
