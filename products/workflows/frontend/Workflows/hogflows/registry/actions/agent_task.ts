import { FEATURE_FLAGS } from 'lib/constants'

import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'Code',
    featureFlag: FEATURE_FLAGS.WORKFLOWS_AGENT_TASK_STEP,
    nodes: [
        {
            type: 'agent_task',
            name: 'Agent task',
            description: 'Start a PostHog Code task with a prompt and wait for it to finish.',
            // Success continues down the branch edge; timeout/failure down the continue edge.
            branchEdges: 1,
            config: {
                prompt: '',
                create_pr: true,
                max_wait_duration: '1h',
            },
        },
    ],
})
