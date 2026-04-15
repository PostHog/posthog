import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'AI',
    nodes: [
        {
            type: 'function',
            name: 'Call LLM',
            description: 'Make an LLM completion request using your API key.',
            config: { template_id: 'template-posthog-llm-completion', inputs: {} },
            output_variable: { key: 'llm_response', result_path: 'content', spread: false },
        },
    ],
})
