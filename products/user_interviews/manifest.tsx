import { IconChat } from '@posthog/icons'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'User interviews',
    scenes: {
        UserInterviews: {
            name: 'User interviews',
            import: () => import('./frontend/UserInterviews'),
            projectBased: true,
            activityScope: 'UserInterview',
        },
        UserInterview: {
            name: 'User interview',
            import: () => import('./frontend/UserInterview'),
            projectBased: true,
            activityScope: 'UserInterview',
        },
    },
    routes: {
        '/user_interviews': ['UserInterviews', 'userInterviews'],
        '/user_interviews/:id': ['UserInterview', 'userInterview'],
    },
    urls: {
        userInterviews: (): string => '/user_interviews',
        userInterview: (id: string): string => `/user_interviews/${id}`,
    },
    fileSystemTypes: {
        user_interview: {
            name: 'User interview',
            icon: <IconChat />,
            href: (ref: string) => urls.userInterview(ref),
            iconColor: ['var(--product-user-interviews-light)'],
            filterKey: 'user_interview',
            flag: FEATURE_FLAGS.USER_INTERVIEWS,
        },
    },
    treeItemsProducts: [
        {
            path: 'User interviews',
            category: 'Behavior',
            href: urls.userInterviews(),
            type: 'user_interview',
            flag: FEATURE_FLAGS.USER_INTERVIEWS,
            tags: ['alpha'],
        },
    ],
}
