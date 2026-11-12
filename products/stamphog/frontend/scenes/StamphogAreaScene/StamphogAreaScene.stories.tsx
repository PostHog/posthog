import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { combineUrl } from 'kea-router'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    PaginatedStamphogRoutingRunListApi,
    StamphogRoutingFileApi,
    StamphogRoutingOwnerCountApi,
    StamphogRoutingRunApi,
    StamphogRoutingRunDetailApi,
    StamphogRoutingRunOwnerApi,
} from '../../generated/api.schemas'

const file = (path: string, additions: number, deletions = 0): StamphogRoutingFileApi => ({
    path,
    previous_path: null,
    status: 'modified',
    additions,
    deletions,
    owners_source: 'owners.yaml',
})

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
        summary: null,
        ...overrides,
    }) as StamphogRoutingRunOwnerApi

interface RunInput {
    id: string
    prNumber: number
    title: string
    author: string
    mergedAt: string
    size: [number, number, number]
    summary: string
    approved: boolean
    owners: StamphogRoutingRunOwnerApi[]
}

const run = ({
    id,
    prNumber,
    title,
    author,
    mergedAt,
    size,
    summary,
    approved,
    owners,
}: RunInput): StamphogRoutingRunApi =>
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
            summary,
            approved_by_stamphog: approved,
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

const storybookSplitFiles = [
    file('common/storybook/.storybook/main.ts', 41, 212),
    file('common/storybook/config/addons.ts', 96),
    file('common/storybook/config/vr.ts', 88),
    file('common/storybook/config/loaders.ts', 64, 12),
    file('common/storybook/config/decorators.ts', 40, 6),
]

const storybookSplit = run({
    id: 'a2',
    prNumber: 83744,
    title: 'chore(devex): split the oversized storybook config module',
    author: 'linus-t',
    mergedAt: '2026-08-14T08:20:00Z',
    size: [329, 230, 5],
    summary:
        'Splits the Storybook config into per-addon modules; story loading and the visual test setup now import from the new paths.',
    approved: true,
    owners: [owner({ lines: 559, file_count: 5 })],
})

const runs: StamphogRoutingRunApi[] = [
    run({
        id: 'a1',
        prNumber: 83799,
        title: 'ci: split backend test shards',
        author: 'ada-l',
        mergedAt: '2026-08-15T19:40:00Z',
        size: [118, 40, 3],
        summary:
            'Moves the backend test matrix from 4 to 6 shards and renames the shard job, so required-check names change.',
        approved: false,
        owners: [
            owner({
                outcome: 'requested',
                reason: 'sensitive',
                pins: [{ reason: 'sensitive', path: '.github/workflows/ci-backend.yml' }],
                lines: 142,
                file_count: 2,
            }),
        ],
    }),
    storybookSplit,
    run({
        id: 'b1',
        prNumber: 83812,
        title: 'feat(hogli): cache the pnpm store between preflight steps',
        author: 'ada-l',
        mergedAt: '2026-08-17T17:30:00Z',
        size: [180, 60, 7],
        summary: 'Caches the pnpm store between preflight steps, so a second preflight run skips the install.',
        approved: true,
        owners: [
            owner({
                lines: 76,
                file_count: 3,
            }),
            owner({ owner: 'team-infra', outcome: 'requested', reason: 'largest_owner', lines: 164, file_count: 4 }),
        ],
    }),
    run({
        id: 'b2',
        prNumber: 83790,
        title: 'fix(hogli): show the failing step name in test output',
        author: 'grace-h',
        mergedAt: '2026-08-16T23:05:00Z',
        size: [50, 18, 3],
        summary: 'hogli test now prints the name of the step that failed instead of only its exit code.',
        approved: true,
        owners: [
            owner({ lines: 22, file_count: 1 }),
            owner({ owner: 'team-clickhouse', outcome: 'cut', reason: 'model_cut', lines: 46, file_count: 2 }),
        ],
    }),
    run({
        id: 'c1',
        prNumber: 83781,
        title: 'feat(devex): add a merge queue lane for docs-only changes',
        author: 'katherine-j',
        mergedAt: '2026-08-16T13:02:00Z',
        size: [210, 90, 8],
        summary: 'Docs-only pull requests get their own merge queue lane, which skips the backend test shards.',
        approved: false,
        owners: [
            owner({
                outcome: 'requested',
                reason: 'model_kept',
                lines: 64,
                file_count: 2,
            }),
            owner({ owner: 'team-docs', outcome: 'requested', reason: 'largest_owner', lines: 236, file_count: 6 }),
        ],
    }),
    run({
        id: 'd1',
        prNumber: 83801,
        title: 'feat(flags): local evaluation payload v2',
        author: 'margaret-h',
        mergedAt: '2026-08-17T12:30:00Z',
        size: [420, 96, 14],
        summary: 'Adds a v2 payload for local evaluation that carries flag dependencies.',
        approved: false,
        owners: [
            owner({
                outcome: 'cut',
                reason: 'model_cut',
                model_reason: 'Only renames an import in a shared test helper.',
                summary: 'renames an import in a shared test helper.',
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
        ],
    }),
    run({
        id: 'd2',
        prNumber: 83770,
        title: 'fix(insights): guard empty series in trend export',
        author: 'alan-t',
        mergedAt: '2026-08-15T16:45:00Z',
        size: [38, 10, 4],
        summary: 'Trend export no longer fails on a series with no data points.',
        approved: false,
        owners: [
            owner({
                outcome: 'cut',
                reason: 'model_cut',
                model_reason: 'A formatting change in a lint config.',
                summary: 'a formatting change in a lint config.',
                lines: 2,
                file_count: 1,
            }),
            owner({
                owner: 'team-product-analytics',
                outcome: 'requested',
                reason: 'largest_owner',
                lines: 46,
                file_count: 3,
            }),
        ],
    }),
]

const page = (results: StamphogRoutingRunApi[]): PaginatedStamphogRoutingRunListApi => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

const owners: StamphogRoutingOwnerCountApi[] = [
    { owner: 'team-devex', kind: 'team', pr_count: 31 },
    { owner: 'team-infra', kind: 'team', pr_count: 24 },
    { owner: 'team-feature-flags', kind: 'team', pr_count: 17 },
    { owner: 'team-product-analytics', kind: 'team', pr_count: 12 },
    { owner: '@octocat', kind: 'person', pr_count: 2 },
]

const storybookSplitDetail = {
    ...storybookSplit,
    owners: [{ ...storybookSplit.owners[0], files: storybookSplitFiles }],
} as StamphogRoutingRunDetailApi

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Stamphog/Your area',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-17 23:30:00',
        // A single scene with no shared component, so the stories render in CI without a visual baseline.
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

const story = (team: string | null, response: PaginatedStamphogRoutingRunListApi): StoryObj => ({
    parameters: { pageUrl: combineUrl(urls.stamphogArea(), team ? { team } : {}).url },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/routing_runs/owners/': owners,
                [`/api/projects/:team_id/stamphog/routing_runs/${storybookSplit.id}/`]: storybookSplitDetail,
                '/api/projects/:team_id/stamphog/routing_runs/': response,
            },
        }),
    ],
})

// Every group, from the pull requests that need a look to small parts of other teams' changes.
export const AllGroups: StoryObj = story('team-devex', page(runs))

// The storybook split opened: the files team-devex owns, and why the team was not asked.
export const ExpandedRow: StoryObj = {
    ...story('team-devex', page(runs)),
    play: async ({ canvasElement }) => {
        const row = (
            await within(canvasElement).findByText(storybookSplit.pull_request.title, {}, { timeout: 15000 })
        ).closest('tr')
        await userEvent.click(within(row!).getByTitle('Show more'))
        await within(canvasElement).findByText('common/storybook/config/decorators.ts', { exact: false })
    },
}

export const TeamPickerOpen: StoryObj = {
    ...story('team-devex', page(runs)),
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText(storybookSplit.pull_request.title, {}, { timeout: 15000 })
        const picker = canvasElement.querySelector<HTMLInputElement>('[data-attr="stamphog-area-team"]')!
        // The input holds the picked team, which filters the list down to that team alone.
        await userEvent.clear(picker)
        await userEvent.type(picker, 'team')
        await within(document.body).findByText('team-infra · 24 PRs')
    },
}

export const Empty: StoryObj = story('team-devex', page([]))

export const NoTeam: StoryObj = story(null, page(runs))
