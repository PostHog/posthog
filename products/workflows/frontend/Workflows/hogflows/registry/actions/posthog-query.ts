import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'Analytics',
    nodes: [
        {
            type: 'function',
            name: 'Run query',
            description: 'Run a HogQL query against PostHog data and store the result.',
            config: { template_id: 'template-posthog-query', inputs: {} },
            output_variable: { key: 'query_result', result_path: null, spread: false },
        },
    ],
})
