import { FEATURE_FLAGS } from 'lib/constants'

import { registerActionNodeCategory } from './actionNodeRegistry'

registerActionNodeCategory({
    label: 'TypeSafe',
    featureFlag: FEATURE_FLAGS.TYPESAFE_WORKFLOW,
    nodes: [
        {
            type: 'function',
            name: 'Classify with TypeSafe',
            description: 'Ask a classification question about selected context. Return the category and confidence.',
            config: { template_id: 'template-typesafe-classify', inputs: {} },
            output_variable: [
                { key: 'typesafe_category', result_path: 'category', label: 'TypeSafe category' },
                { key: 'typesafe_confidence', result_path: 'confidence', label: 'TypeSafe confidence' },
            ],
            defaultVariables: [
                { key: 'typesafe_category', type: 'string', label: 'TypeSafe category', default: '' },
                { key: 'typesafe_confidence', type: 'number', label: 'TypeSafe confidence', default: 0 },
            ],
        },
    ],
})
