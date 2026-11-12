import type { Meta, StoryObj } from '@storybook/react'
import { combineUrl } from 'kea-router'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    PaginatedStamphogRoutingRunListApi,
    StamphogRoutingRunApi,
    StamphogRoutingRunOwnerApi,
} from '../../generated/api.schemas'

const owner = (overrides: Partial<StamphogRoutingRunOwnerApi>): StamphogRoutingRunOwnerApi =>
    ({
        owner: 'team-devex',
        kind: 'team',
        outcome: 'not_requested',
        reason: 'model_kept',
        model_reason: '',
        pins: [],
        lines: 42,
        file_count: 3,
        ...overrides,
    }) as StamphogRoutingRunOwnerApi

const run = (
    id: string,
    prNumber: number,
    title: string,
    author: string,
    mergedAt: string,
    size: [number, number, number],
    owners: StamphogRoutingRunOwnerApi[]
): StamphogRoutingRunApi =>
    ({
        id: `00000000-0000-0000-0000-0000000000${id}`,
        repository: 'PostHog/posthog',
        pr_number: prNumber,
        pull_request: {
            title,
            author,
            url: `https://github.com/PostHog/posthog/pull/${prNumber}`,
            merged_at: mergedAt,
            additions: size[0],
            deletions: size[1],
            changed_files: size[2],
        },
        head_sha: 'a91f3cd8e2b1447fa0c2d9e5b7318fa4c02d1e77',
        mode: 'fallback',
        trigger: 'verdict:approved',
        scope: 'pinned',
        fork: false,
        llm_skipped: null,
        model: 'claude-haiku-5-5',
        files_truncated: false,
        additions_resolved: true,
        owners_sha: '4fe8b2077c1a9e3d5b06f8241ac93de70b115f6a',
        owners,
        created_at: '2026-08-13T09:12:00Z',
    }) as StamphogRoutingRunApi

const page = (results: StamphogRoutingRunApi[]): PaginatedStamphogRoutingRunListApi => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

const wouldHaveBeenAsked = page([
    run(
        'b1',
        83812,
        'chore(devex): cache pnpm store between preflight steps',
        'ada-l',
        '2026-08-17T15:40:00Z',
        [64, 12, 3],
        [
            owner({ lines: 76, file_count: 3 }),
            owner({
                owner: 'team-infra',
                outcome: 'cut',
                reason: 'model_cut',
                model_reason: 'Only touches a workflow comment.',
            }),
        ]
    ),
    run(
        'b2',
        83790,
        'fix(hogli): show the failing step name in test output',
        'grace-h',
        '2026-08-16T11:05:00Z',
        [18, 4, 1],
        [owner({ lines: 22, file_count: 1 })]
    ),
    run(
        'b3',
        83744,
        'chore(devex): split the oversized storybook config module',
        'linus-t',
        '2026-08-14T08:20:00Z',
        [310, 288, 9],
        [owner({ reason: 'largest_owner', lines: 598, file_count: 9 })]
    ),
])

const cutByTheModel = page([
    run(
        'c1',
        83801,
        'feat(flags): local evaluation payload v2',
        'margaret-h',
        '2026-08-17T10:30:00Z',
        [420, 96, 14],
        [
            owner({
                outcome: 'cut',
                reason: 'model_cut',
                model_reason: 'Only renames an import in a shared test helper.',
                lines: 4,
                file_count: 1,
            }),
            owner({
                owner: 'team-feature-flags',
                outcome: 'requested',
                reason: 'largest_owner',
                lines: 512,
                file_count: 13,
            }),
        ]
    ),
    run(
        'c2',
        83770,
        'fix(insights): guard empty series in trend export',
        'alan-t',
        '2026-08-15T16:45:00Z',
        [38, 10, 4],
        [
            owner({
                outcome: 'cut',
                reason: 'model_cut',
                model_reason: 'Formatting change in a lint config it owns.',
                lines: 2,
                file_count: 1,
            }),
        ]
    ),
])

const asked = page([
    run(
        'd1',
        83799,
        'feat(devex): add a merge queue lane for docs-only changes',
        'katherine-j',
        '2026-08-17T13:02:00Z',
        [140, 22, 5],
        [
            owner({
                outcome: 'requested',
                reason: 'sensitive',
                pins: [{ reason: 'sensitive', path: '.github/workflows/ci-backend.yml' }],
                lines: 162,
                file_count: 5,
            }),
        ]
    ),
])

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Stamphog/Team view',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-17 23:30:00',
        // A single scene with no shared component, so the stories render in CI without a visual baseline.
        testOptions: { waitForSelector: '[data-attr="stamphog-team-view-count"]', snapshotBrowsers: [] },
    },
}
export default meta

const story = (outcome: string, response: PaginatedStamphogRoutingRunListApi): StoryObj => ({
    parameters: { pageUrl: combineUrl(urls.stamphogTeamView(), { team: 'team-devex', outcome }).url },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/stamphog/routing_runs/': response } })],
})

// Pull requests stamphog approved that routing would otherwise have sent to team-devex.
export const WouldHaveBeenAsked: StoryObj = story('not_requested', wouldHaveBeenAsked)

// The model judged team-devex's part too small to need its review, with the reason on each row.
export const CutByTheModel: StoryObj = story('cut', cutByTheModel)

// team-devex was asked, here because the pull request changed a sensitive path it owns.
export const Asked: StoryObj = story('requested', asked)
