import { FEATURE_FLAGS } from 'lib/constants'

import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'In-app',
    featureFlag: FEATURE_FLAGS.WORKFLOWS_SURVEY_STEP,
    nodes: [
        {
            type: 'function',
            name: 'Show survey',
            description: 'Show an in-app survey the next time this person opens your app.',
            config: { template_id: 'template-posthog-show-survey', inputs: {} },
        },
    ],
})
