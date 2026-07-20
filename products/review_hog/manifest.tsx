import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'ReviewHog',
    scenes: {
        CodeReview: {
            name: 'Code review',
            import: () => import('./frontend/CodeReviewScene'),
            projectBased: true,
            description: 'Automated code reviews of your pull requests, and your review agent settings.',
            iconType: 'code_review',
        },
    },
    routes: {
        '/code_review': ['CodeReview', 'codeReview'],
    },
    urls: {
        codeReview: (): string => '/code_review',
    },
    treeItemsProducts: [
        {
            path: 'Code review',
            intents: [ProductKey.REVIEW_HOG],
            category: ProductItemCategory.UNRELEASED,
            iconType: 'code_review' as FileSystemIconType,
            href: urls.codeReview(),
            flag: FEATURE_FLAGS.REVIEW_HOG,
            tags: ['alpha'],
            sceneKey: 'CodeReview',
        },
    ],
}
