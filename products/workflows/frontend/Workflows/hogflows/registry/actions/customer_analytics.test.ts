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

    it('stores the account in a single variable without spreading', () => {
        const node = getCategory().nodes.find((n) => n.name === 'Get account')
        expect(node?.output_variable).toEqual({ key: 'account', result_path: null })
    })

    it('wires the Update account node to its hog function template', () => {
        const node = getCategory().nodes.find((n) => n.name === 'Update account')
        expect(node).toMatchObject({
            type: 'function',
            config: { template_id: 'template-posthog-update-account' },
        })
    })
})
