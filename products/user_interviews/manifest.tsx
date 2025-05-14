import { IconChat } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'User interviews',
    urls: {
        userInterviews: (): string => '/user_interviews',
        userInterview: (id: string): string => `/user_interviews/${id}`,
    },
    fileSystemTypes: {
        user_interview: {
            icon: <IconChat />,
            href: (ref: string) => urls.userInterview(ref),
        },
    },
    treeItemsProducts: [
        {
            path: 'User interviews',
            href: urls.userInterviews(),
            type: 'user_interview',
        },
    ],
    fileSystemFilterTypes: {
        user_interview: { name: 'User interviews' },
    },
}
