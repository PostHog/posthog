import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'Claude',
    nodes: [
        {
            type: 'function',
            name: 'Run Claude managed agent',
            description: 'Start a Claude managed agent session and capture the session id.',
            config: { template_id: 'template-claude-managed-agent', inputs: {} },
            output_variable: { key: 'claude_session', result_path: null, spread: true },
        },
    ],
})
