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
        VisualReviewSnapshotHistory: {
            name: 'Visual review snapshot history',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewSnapshotHistoryScene'),
            iconType: 'visual_review',
        },
    },
    routes: {
        '/visual_review': ['VisualReviewRuns', 'visualReviewRuns'],
        '/visual_review/settings': ['VisualReviewSettings', 'visualReviewSettings'],
        '/visual_review/runs/:runId': ['VisualReviewRun', 'visualReviewRun'],
        '/visual_review/repos/:repoId/:runType/snapshots/:identifier': [
            'VisualReviewSnapshotHistory',
            'visualReviewSnapshotHistory',
        ],
    },
    redirects: {},
    urls: {
        visualReviewRuns: (): string => '/visual_review',
        visualReviewSettings: (): string => '/visual_review/settings',
        visualReviewRun: (runId: string): string => `/visual_review/runs/${runId}`,
        visualReviewSnapshotHistory: (repoId: string, runType: string, identifier: string): string =>
            `/visual_review/repos/${repoId}/${encodeURIComponent(runType)}/snapshots/${encodeURIComponent(identifier)}`,
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
