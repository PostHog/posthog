import { FEATURE_FLAGS } from 'lib/constants'

import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'Feature flags',
    featureFlag: FEATURE_FLAGS.WORKFLOWS_FEATURE_FLAGS_ACTION,
    nodes: [
        {
            type: 'function',
            name: 'Get feature flags',
            description: 'Find feature flags by status, age, or release condition.',
            config: { template_id: 'template-posthog-get-feature-flags', inputs: {} },
            output_variable: { key: 'feature_flags', result_path: null, label: 'Feature flags' },
        },
    ],
})
