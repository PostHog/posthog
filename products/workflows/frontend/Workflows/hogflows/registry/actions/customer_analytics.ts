import { FEATURE_FLAGS } from 'lib/constants'

import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'Customer analytics',
    featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    nodes: [
        {
            type: 'function',
            name: 'Get account',
            description: 'Fetch a Customer analytics account into a workflow variable.',
            config: { template_id: 'template-posthog-get-account', inputs: {} },
            output_variable: { key: 'account', result_path: null, spread: true },
        },
    ],
})
