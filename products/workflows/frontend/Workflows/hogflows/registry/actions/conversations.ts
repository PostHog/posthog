import { FEATURE_FLAGS } from 'lib/constants'

import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'Support',
    featureFlag: FEATURE_FLAGS.PRODUCT_SUPPORT,
    nodes: [
        {
            type: 'function',
            name: 'Get ticket',
            description: 'Fetch current ticket data into a workflow variable.',
            config: { template_id: 'template-posthog-get-ticket', inputs: {} },
            output_variable: { key: 'ticket', result_path: null, spread: true },
        },
        {
            type: 'function',
            name: 'Update ticket',
            description: 'Update a conversation ticket status or priority.',
            config: { template_id: 'template-posthog-update-ticket', inputs: {} },
        },
    ],
})
