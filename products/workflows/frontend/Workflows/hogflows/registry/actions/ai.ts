import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'AI',
    nodes: [
        {
            type: 'function',
            name: 'LLM classify',
            description:
                'Run an LLM classification on the triggering event and store the result for downstream branches.',
            // User-facing inputs: model, instructions, content, categories. Gateway URL + auth are
            // resolved server-side by the postHogLLMClassify async function so users never have to
            // touch a personal API key or know which region the gateway lives in.
            config: { template_id: 'template-posthog-llm-classify', inputs: {} },
            // `spread: true` flattens the parsed `{ category, reasoning }` (or `{ content }` for
            // free-form mode) onto the workflow variable so `conditional_branch` can compare
            // `classification.category` directly without an extra unwrap step.
            output_variable: { key: 'classification', result_path: null, spread: true },
        },
    ],
})
