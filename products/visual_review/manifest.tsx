/**
 * Product manifest for visual_review.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'VisualReview',
    scenes: {
        VisualReviewRuns: {
            name: 'Visual review',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewRunsScene'),
            iconType: 'visual_review',
        },
        VisualReviewRun: {
            name: 'Visual review run',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewRunScene'),
            iconType: 'visual_review',
        },
        VisualReviewSettings: {
            name: 'Visual review settings',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewSettingsScene'),
            iconType: 'visual_review',
        },
    },
    routes: {
        '/visual_review': ['VisualReviewRuns', 'visualReviewRuns'],
        '/visual_review/settings': ['VisualReviewSettings', 'visualReviewSettings'],
        '/visual_review/runs/:runId': ['VisualReviewRun', 'visualReviewRun'],
    },
    redirects: {},
    urls: {
        visualReviewRuns: (): string => '/visual_review',
        visualReviewSettings: (): string => '/visual_review/settings',
        visualReviewRun: (runId: string): string => `/visual_review/runs/${runId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Visual review',
            intents: [ProductKey.VISUAL_REVIEW],
            category: 'Unreleased',
            href: urls.visualReviewRuns(),
            iconType: 'visual_review' as FileSystemIconType,
            tags: ['alpha'],
            sceneKey: 'VisualReviewRuns',
        },
    ],
}
