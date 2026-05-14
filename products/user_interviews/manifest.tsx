import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'User research',
    scenes: {
        UserInterviews: {
            name: 'User research',
            import: () => import('./frontend/UserInterviews'),
            projectBased: true,
            activityScope: 'UserInterview',
            description: 'Run AI-powered voice research campaigns to gather user insights at scale.',
            iconType: 'user_interview',
        },
        UserInterview: {
            name: 'Interview topic',
            import: () => import('./frontend/UserInterview'),
            projectBased: true,
            activityScope: 'UserInterview',
        },
        UserInterviewResponse: {
            name: 'Interview response',
            import: () => import('./frontend/UserInterviewResponse'),
            projectBased: true,
            activityScope: 'UserInterview',
        },
    },
    routes: {
        '/user_research': ['UserInterviews', 'userInterviews'],
        '/user_research/:topicId/response/:responseId': ['UserInterviewResponse', 'userInterviewResponse'],
        '/user_research/:id': ['UserInterview', 'userInterview'],
    },
    redirects: {
        '/user_interviews': '/user_research',
    },
    urls: {
        userInterviews: (): string => '/user_research',
        userInterview: (id: string): string => `/user_research/${id}`,
        userInterviewResponse: (topicId: string, responseId: string): string =>
            `/user_research/${topicId}/response/${responseId}`,
    },
    fileSystemTypes: {
        user_interview: {
            name: 'User research',
            iconType: 'user_interview',
            href: (ref: string) => urls.userInterview(ref),
            iconColor: ['var(--color-product-user-interviews-light)'],
            filterKey: 'user_interview',
            flag: FEATURE_FLAGS.USER_INTERVIEWS,
        },
    },
    treeItemsProducts: [
        {
            path: 'User research',
            intents: [ProductKey.USER_INTERVIEWS],
            category: ProductItemCategory.UNRELEASED,
            href: urls.userInterviews(),
            type: 'user_interview',
            flag: FEATURE_FLAGS.USER_INTERVIEWS,
            tags: ['alpha'],
            iconType: 'user_interview',
            iconColor: ['var(--color-product-user-interviews-light)'] as FileSystemIconColor,
            sceneKey: 'UserInterviews',
        },
    ],
}
