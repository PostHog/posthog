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
        VisualReviewIndex: {
            // /visual_review entry point — picks a repo and forwards into its
            // workspace. Empty / multi-repo cases handled inside the scene.
            name: 'Visual review',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewIndexScene'),
            iconType: 'visual_review',
        },
        VisualReviewRuns: {
            name: 'Runs',
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
        VisualReviewSnapshotOverview: {
            name: 'Snapshots',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewSnapshotOverviewScene'),
            iconType: 'visual_review',
        },
    },
    routes: {
        '/visual_review': ['VisualReviewIndex', 'visualReviewIndex'],
        '/visual_review/settings': ['VisualReviewSettings', 'visualReviewSettings'],
        '/visual_review/runs/:runId': ['VisualReviewRun', 'visualReviewRun'],
        '/visual_review/repos/:repoId/runs': ['VisualReviewRuns', 'visualReviewRepoRuns'],
        '/visual_review/repos/:repoId/snapshots': ['VisualReviewSnapshotOverview', 'visualReviewSnapshotOverview'],
        '/visual_review/repos/:repoId/:runType/snapshots/:identifier': [
            'VisualReviewSnapshotHistory',
            'visualReviewSnapshotHistory',
        ],
    },
    redirects: {},
    urls: {
        // Entry URL — the index scene resolves a repo and forwards into the
        // workspace. Sidebar/nav callers stay zero-arg as before.
        visualReviewRuns: (): string => '/visual_review',
        visualReviewSettings: (): string => '/visual_review/settings',
        visualReviewRun: (runId: string): string => `/visual_review/runs/${runId}`,
        visualReviewRepoRuns: (repoId: string): string => `/visual_review/repos/${repoId}/runs`,
        visualReviewSnapshotOverview: (repoId: string): string => `/visual_review/repos/${repoId}/snapshots`,
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
            sceneKey: 'VisualReviewIndex',
        },
    ],
}
