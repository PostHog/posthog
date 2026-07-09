import { FEATURE_FLAGS } from 'lib/constants'

import { GroupType, GroupTypeIndex } from '~/types'

import { getRegisteredActionNodeCategories } from './actionNodeRegistry'
import {
    buildAccountExternalIdInputs,
    buildAccountOutputSuggestions,
    customPropertyResultPath,
    slugifyName,
} from './customer_analytics'

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
            key: 'account_relationships',
            result_path: 'relationships',
            label: 'Relationships',
        })
        expect(outputVars).toContainEqual({
            key: 'account_slack_channel_id',
            result_path: 'properties.slack_channel_id',
            label: 'Slack channel ID',
        })

        expect(outputVars.map((v) => v.key)).toEqual([
            'account',
            'account_relationships',
            'account_stripe_customer_id',
            'account_hubspot_deal_id',
            'account_billing_id',
            'account_sfdc_id',
            'account_zendesk_id',
            'account_slack_channel_id',
        ])
    })

    it('does not include the old Update account node in the picker', () => {
        const node = getCategory().nodes.find((n) => n.name === 'Update account')
        expect(node).toBeUndefined()
    })

    it('wires the Tag account node to its hog function template', () => {
        const node = getCategory().nodes.find((n) => n.name === 'Tag account')
        expect(node).toMatchObject({
            type: 'function',
            config: { template_id: 'template-posthog-tag-account' },
        })
    })

    it('wires the Update account relationships node to its hog function template', () => {
        const node = getCategory().nodes.find((n) => n.name === 'Update account relationships')
        expect(node).toMatchObject({
            type: 'function',
            config: { template_id: 'template-posthog-update-account-relationships' },
        })
    })

    it.each(['Get account', 'Tag account', 'Update account relationships'])(
        'gives %s a dynamic external_id default resolver',
        (name) => {
            const node = getCategory().nodes.find((n) => n.name === name)
            expect(typeof node?.getDefaultInputs).toBe('function')
        }
    )

    describe('slugifyName', () => {
        it.each([
            ['Plan', 'plan'],
            ['MRR (net)', 'mrr_net'],
            ['ARR (net)', 'arr_net'],
            ['my_property', 'my_property'],
            ['  spaces  ', 'spaces'],
            ['a--b', 'a_b'],
        ])('slugifies %s → %s', (input, expected) => {
            expect(slugifyName(input)).toBe(expected)
        })
    })

    describe('customPropertyResultPath', () => {
        it.each([
            ['Plan', 'custom_properties.Plan'],
            ['my_prop', 'custom_properties.my_prop'],
            ['ARR123', 'custom_properties.ARR123'],
            ['MRR (net)', 'custom_properties["MRR (net)"]'],
            ['has space', 'custom_properties["has space"]'],
            ['with"quote', 'custom_properties["with\\"quote"]'],
        ])('builds result path for %s → %s', (name, expected) => {
            expect(customPropertyResultPath(name)).toBe(expected)
        })
    })

    describe('buildAccountOutputSuggestions', () => {
        it('namespaces relationships and dedupes colliding keys', () => {
            const suggestions = buildAccountOutputSuggestions(['Plan', 'MRR (net)', 'MRR net'], ['Plan', 'CSM'])
            expect(suggestions.map((s) => s.key)).toEqual([
                'account_plan',
                'account_mrr_net',
                'account_relationship_plan',
                'account_relationship_csm',
            ])
            expect(suggestions.find((s) => s.key === 'account_relationship_csm')?.result_path).toBe(
                'relationships["CSM"]'
            )
        })
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
