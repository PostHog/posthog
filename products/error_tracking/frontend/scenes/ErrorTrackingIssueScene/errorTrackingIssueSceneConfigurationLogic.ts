import { actions, defaults, kea, path, reducers } from 'kea'

import type { errorTrackingIssueSceneConfigurationLogicType } from './errorTrackingIssueSceneConfigurationLogicType'

export type ErrorTrackingIssueSceneCategory = 'exceptions' | 'breakdowns' | 'autofix' | 'similar_issues'

export const errorTrackingIssueSceneConfigurationLogic = kea<errorTrackingIssueSceneConfigurationLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingIssueScene',
        'errorTrackingIssueSceneConfigurationLogic',
    ]),

    actions({
        setCategory: (category: ErrorTrackingIssueSceneCategory) => ({ category }),
    }),

    defaults({
        category: 'exceptions' as ErrorTrackingIssueSceneCategory,
    }),

    reducers(() => ({
        category: {
            setCategory: (_, { category }) => category,
        },
    })),
])
