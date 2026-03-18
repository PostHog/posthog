import { actions, defaults, kea, path, reducers } from 'kea'

import type { errorTrackingIssueSceneConfigurationLogicType } from './errorTrackingIssueSceneConfigurationLogicType'

export type ErrorTrackingIssueSceneCategory = 'exceptions' | 'breakdowns' | 'autofix' | 'similar_issues'

export const VALID_CATEGORIES: ErrorTrackingIssueSceneCategory[] = [
    'exceptions',
    'breakdowns',
    'autofix',
    'similar_issues',
]
export const DEFAULT_CATEGORY: ErrorTrackingIssueSceneCategory = 'exceptions'

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
        category: DEFAULT_CATEGORY as ErrorTrackingIssueSceneCategory,
    }),

    reducers(() => ({
        category: {
            setCategory: (_, { category }) => category,
        },
    })),
])
