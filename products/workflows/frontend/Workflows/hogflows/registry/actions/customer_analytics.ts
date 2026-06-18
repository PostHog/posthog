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
            // No `spread`: the editor's spread helper (hogFlowEditorLogic) hardcodes ticket field
            // names, so it can't flatten an account. Store the whole object in one variable instead.
            output_variable: { key: 'account', result_path: null },
        },
        {
            type: 'function',
            name: 'Update account',
            description: 'Assign role contacts or tag a Customer analytics account.',
            config: { template_id: 'template-posthog-update-account', inputs: {} },
            output_variable: { key: 'account', result_path: null },
        },
    ],
})
