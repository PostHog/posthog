import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'

import { mswDecorator } from '~/mocks/browser'

import type { ArtifactApi, RepoApi, RunApi, SnapshotApi } from '../generated/api.schemas'

const RUN_ID = '00000000-0000-0000-0000-0000000000aa'
const REPO_ID = '00000000-0000-0000-0000-0000000000bb'

// A deterministic 1x1 PNG so the diff viewer renders without hitting the network.
const PIXEL =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

const artifact = (contentHash: string): ArtifactApi => ({
    id: `artifact-${contentHash}`,
    content_hash: contentHash,
    width: 320,
    height: 200,
    download_url: PIXEL,
})

const repo: RepoApi = {
    id: REPO_ID,
    team_id: 1,
    repo_external_id: 99999,
    repo_full_name: 'PostHog/posthog',
    baseline_file_paths: {},
    enable_pr_comments: true,
    created_at: '2026-06-10T00:00:00Z',
}

const run: RunApi = {
    id: RUN_ID,
    repo_id: REPO_ID,
    status: 'completed',
    run_type: 'storybook',
    commit_sha: 'cafef00dcafef00d',
    branch: 'feature/new-button',
    pr_number: 42,
    approved: false,
    approved_at: null,
    summary: { total: 7, changed: 1, new: 1, removed: 0, unchanged: 5 },
    error_message: null,
    created_at: '2026-06-10T00:00:00Z',
    completed_at: '2026-06-10T00:01:00Z',
    is_stale: false,
    metadata: {},
    search_match_type: null,
}

const snapshot = (overrides: Partial<SnapshotApi>): SnapshotApi => ({
    id: 'snapshot-default',
    run_id: RUN_ID,
    identifier: 'Components/Button--primary',
    result: 'changed',
    classification_reason: '',
    diff_percentage: 2.4,
    diff_pixel_count: 1536,
    review_state: 'pending',
    reviewed_at: null,
    approved_hash: '',
    ...overrides,
})

const snapshots = {
    count: 2,
    next: null,
    previous: null,
    quarantined_count: 0,
    results: [
        snapshot({
            id: 'snapshot-changed',
            identifier: 'Components/Button--primary',
            result: 'changed',
            baseline_artifact: artifact('base_changed'),
            current_artifact: artifact('curr_changed'),
        }),
        snapshot({
            id: 'snapshot-new',
            identifier: 'Components/Banner--info',
            result: 'new',
            diff_percentage: null,
            diff_pixel_count: null,
            current_artifact: artifact('curr_new'),
        }),
    ],
}

// A push to the default branch — no PR, tracking-only. Nothing to approve.
const masterRun: RunApi = {
    ...run,
    branch: 'master',
    pr_number: null,
}

const emptyList = { count: 0, next: null, previous: null, results: [] }

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Visual review/Run',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-10',
        pageUrl: `/visual_review/runs/${RUN_ID}`,
        testOptions: { waitForSelector: '[data-attr="visual-review-add-images-to-comment"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/`]: run,
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/snapshots/`]: snapshots,
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/tolerated-hashes/`]: emptyList,
                [`/api/projects/:team_id/visual_review/repos/${REPO_ID}/`]: repo,
                [`/api/projects/:team_id/visual_review/repos/${REPO_ID}/quarantine/`]: emptyList,
            },
        }),
    ],
}
export default meta

// The finalize action carries an opt-in "Also comment on the PR" checkbox beside it.
export const ReadyToFinalize: StoryObj = {}

// A default-branch run is reporting-only: no finalize action, no per-snapshot accept/reject/tolerate —
// just an informational banner. Snapshots still have changes, but there's nothing to approve.
export const TrackingOnlyMasterRun: StoryObj = {
    parameters: {
        testOptions: { waitForSelector: '[data-attr="visual-review-snapshot-thumbnail"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/`]: masterRun,
            },
        }),
    ],
}
