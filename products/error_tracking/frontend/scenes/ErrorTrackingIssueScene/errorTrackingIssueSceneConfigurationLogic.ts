import { actions, defaults, kea, path, reducers } from 'kea'

export type ErrorTrackingIssueSceneCategory = 'overview' | 'exceptions' | 'breakdowns' | 'autofix' | 'similar_issues'

export const errorTrackingIssueSceneConfigurationLogic = kea<errorTrackingIssueSceneConfigurationLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingIssueScene',
        'errorTrackingIssueSceneConfigurationLogic',
    ]),

    actions({
        isSidebarOpen: (isOpen: boolean) => ({ isOpen }),
        setCategory: (category: ErrorTrackingIssueSceneCategory) => ({ category }),
    }),

    defaults({
        isSidebarOpen: true as boolean,
        category: 'overview' as ErrorTrackingIssueSceneCategory,
    }),

    reducers(() => ({
        isSidebarOpen: {
            setIsSidebarOpen: (_, { isOpen }) => isOpen,
        },
        category: {
            setCategory: (_, { category }) => category,
        },
    })),
])
