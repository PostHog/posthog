import { actions, defaults, kea, path, reducers } from 'kea'

import type { errorTrackingIssueSceneConfigurationLogicType } from './errorTrackingIssueSceneConfigurationLogicType'

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
        setIsSidebarOpen: (isOpen: boolean) => ({ isOpen }),
        setCategory: (category: ErrorTrackingIssueSceneCategory) => ({ category }),
        openSidebar: (category: ErrorTrackingIssueSceneCategory) => ({ category }),
    }),

    defaults({
        isSidebarOpen: true as boolean,
        category: 'overview' as ErrorTrackingIssueSceneCategory,
    }),

    reducers(() => ({
        isSidebarOpen: {
            setIsSidebarOpen: (_, { isOpen }) => isOpen,
            openSidebar: () => true,
        },
        category: {
            setCategory: (_, { category }) => category,
            openSidebar: (_, { category }) => category,
        },
    })),
])
