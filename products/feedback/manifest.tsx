import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Feedback',
    scenes: {
        FeedbackList: {
            import: () => import('./frontend/scenes/FeedbackListScene/FeedbackListScene'),
            name: 'Feedback',
            projectBased: true,
        },
        FeedbackItem: {
            import: () => import('./frontend/scenes/FeedbackItemScene/FeedbackItemScene'),
            name: 'Feedback item',
            projectBased: true,
        },
    },
    routes: {
        '/feedback': ['FeedbackList', 'feedbackList'],
        '/feedback/:id': ['FeedbackItem', 'feedbackItem'],
    },
    urls: {
        feedbackList: (): string => '/feedback',
        feedbackItem: (id: string): string => `/feedback/${id}`,
    },
    fileSystemTypes: {
        feedback: {
            name: 'Feedback',
            iconType: 'comment',
            href: () => urls.feedbackList(),
            iconColor: ['var(--color-product-feature-flags-light)'],
            filterKey: 'feedback',
        },
    },
    treeItemsProducts: [
        {
            path: `Feedback`,
            category: 'Behavior',
            type: 'feedback',
            href: urls.feedbackList(),
        },
    ],
}
