/**
 * Product manifest for visual_review.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { ProductItemCategory } from '../../frontend/src/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'VisualReview',
    scenes: {
        VisualReviewIndex: {
            // /visual_review entry point — picks a repo and forwards into its
            // workspace. Empty / multi-repo cases handled inside the scene.
            name: 'Visual review',
            description:
                'Catch unintended UI changes by reviewing screenshot diffs from CI, with the approved baselines committed back to your repo.',
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
        VisualReviewFlakiness: {
            name: 'Flakiness',
            projectBased: true,
            import: () => import('./frontend/scenes/VisualReviewFlakinessScene'),
            iconType: 'visual_review',
        },
    },
    routes: {
        '/visual-review': ['VisualReviewIndex', 'visualReviewIndex'],
        '/visual-review/settings': ['VisualReviewSettings', 'visualReviewSettings'],
        '/visual-review/repos/:repoOwner/:repoName/runs': ['VisualReviewRuns', 'visualReviewRepoRuns'],
        '/visual-review/repos/:repoOwner/:repoName/runs/:runId': ['VisualReviewRun', 'visualReviewRun'],
        '/visual-review/repos/:repoOwner/:repoName/snapshots': [
            'VisualReviewSnapshotOverview',
            'visualReviewSnapshotOverview',
        ],
        '/visual-review/repos/:repoOwner/:repoName/flakiness': ['VisualReviewFlakiness', 'visualReviewFlakiness'],
        '/visual-review/repos/:repoOwner/:repoName/:runType/snapshots/:identifier': [
            'VisualReviewSnapshotHistory',
            'visualReviewSnapshotHistory',
        ],
        // URLs that name a repo or run by UUID. PR comments and bookmarks still carry them, so the index
        // scene looks the repo up and forwards to its owner/name URL.
        '/visual-review/runs/:runId': ['VisualReviewIndex', 'visualReviewLegacyRun'],
        '/visual-review/repos/:repoId/runs': ['VisualReviewIndex', 'visualReviewLegacyRepoRuns'],
        '/visual-review/repos/:repoId/snapshots': ['VisualReviewIndex', 'visualReviewLegacySnapshotOverview'],
        '/visual-review/repos/:repoId/flakiness': ['VisualReviewIndex', 'visualReviewLegacyFlakiness'],
        '/visual-review/repos/:repoId/:runType/snapshots/:identifier': [
            'VisualReviewIndex',
            'visualReviewLegacySnapshotHistory',
        ],
    },
    // The product shipped under /visual_review. PR comments, commit statuses, digests and older
    // CLI builds link there, so every old path forwards and keeps its search and hash params.
    // The rest of the path passes through still URL-encoded, so nothing is encoded twice.
    redirects: {
        '/visual_review': (_params, searchParams, hashParams): string =>
            combineUrl(urls.visualReviewRuns(), searchParams, hashParams).url,
        '/visual_review/*': ({ _ }, searchParams, hashParams): string =>
            combineUrl(`/visual-review/${_}`, searchParams, hashParams).url,
    },
    urls: {
        // Entry URL — the index scene resolves a repo and forwards into the
        // workspace. Sidebar/nav callers stay zero-arg as before.
        visualReviewRuns: (): string => '/visual-review',
        visualReviewSettings: (): string => '/visual-review/settings',
        // The run path that names no repository. It forwards once the run says which repository it belongs to.
        visualReviewRun: (runId: string): string => `/visual-review/runs/${runId}`,
        visualReviewRepoRun: (repoOwner: string, repoName: string, runId: string): string =>
            `/visual-review/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/runs/${runId}`,
        visualReviewRepoRuns: (repoOwner: string, repoName: string): string =>
            `/visual-review/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/runs`,
        visualReviewSnapshotOverview: (repoOwner: string, repoName: string): string =>
            `/visual-review/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/snapshots`,
        visualReviewFlakiness: (repoOwner: string, repoName: string): string =>
            `/visual-review/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/flakiness`,
        visualReviewSnapshotHistory: (
            repoOwner: string,
            repoName: string,
            runType: string,
            identifier: string
        ): string =>
            `/visual-review/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/${encodeURIComponent(runType)}/snapshots/${encodeURIComponent(identifier)}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Visual review',
            intents: [ProductKey.VISUAL_REVIEW],
            category: ProductItemCategory.UNRELEASED,
            href: urls.visualReviewRuns(),
            searchKeywords: ['visual regression', 'screenshot diffs', 'baselines'],
            iconType: 'visual_review' as FileSystemIconType,
            iconColor: [
                'var(--color-product-visual-review-light)',
                'var(--color-product-visual-review-dark)',
            ] as FileSystemIconColor,
            flag: FEATURE_FLAGS.VISUAL_REVIEW,
            tags: ['alpha'],
            sceneKey: 'VisualReviewIndex',
        },
    ],
}
