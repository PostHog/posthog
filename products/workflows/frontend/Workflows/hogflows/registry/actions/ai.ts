import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'AI',
    nodes: [
        {
            type: 'llm',
            name: 'LLM prompt',
            description: 'Send a prompt to an LLM and store the response in a workflow variable.',
            config: {
                model: 'openai/gpt-4o-mini',
                messages: [{ role: 'user', content: { value: '', templating: 'liquid' } }],
                max_wait_duration: '5m',
            },
            output_variable: { key: 'llm_response', result_path: 'text', spread: false },
        },
    ],
})
