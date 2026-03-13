import { FEATURE_FLAGS } from 'lib/constants'

import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'AI',
    featureFlag: FEATURE_FLAGS.WORKFLOW_AI_AGENT,
    nodes: [
        {
            type: 'function',
            name: 'Run AI agent',
            description: 'Run an AI agent to analyze data or answer questions.',
            config: {
                template_id: 'template-posthog-run-agent',
                inputs: {
                    agent_config: {
                        value: {
                            prompt: '',
                            github_installation: null,
                            repository: null,
                            output_schema: null,
                        },
                    },
                },
            },
            output_variable: { key: 'agent_result', result_path: null, spread: false },
        },
    ],
})
