/**
 * Product manifest for visual_review.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { ProductItemCategory } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'VisualReview',
    scenes: {
        VisualReviewRuns: {
            name: 'Visual review',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewRunsScene'),
            iconType: 'visual_review',
            settingsSection: 'environment-visual-review',
        },
        VisualReviewRun: {
            name: 'Visual review run',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewRunScene'),
            iconType: 'visual_review',
            settingsSection: 'environment-visual-review',
        },
    },
    routes: {
        '/visual_review': ['VisualReviewRuns', 'visualReviewRuns'],
        '/visual_review/runs/:runId': ['VisualReviewRun', 'visualReviewRun'],
    },
    urls: {
        visualReviewRuns: (): string => '/visual_review',
        visualReviewRun: (runId: string): string => `/visual_review/runs/${runId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Visual review',
            intents: [ProductKey.VISUAL_REVIEW],
            category: ProductItemCategory.UNRELEASED,
            href: urls.visualReviewRuns(),
            iconType: 'visual_review' as FileSystemIconType,
            flag: FEATURE_FLAGS.VISUAL_REVIEW,
            tags: ['alpha'],
            sceneKey: 'VisualReviewRuns',
        },
    ],
}
