import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind, type RecordingsQuery } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import { ReplayFiltersScannerPopover } from './ReplayFiltersScannerPopover'

const quota = {
    credit_limit: 10000,
    credits_used: 100,
    remaining: 9900,
    exhausted: false,
    projected_monthly_credits: 0,
    scanners_monthly_credits: 0,
    backfills_committed_credits: 0,
    free_monthly_credits: 2500,
    credits_settled: 100,
    credits_reserved: 0,
    period_start: '2026-10-01T00:00:00Z',
    period_end: '2026-11-01T00:00:00Z',
}

const withFiltersQuery: RecordingsQuery = {
    kind: NodeKind.RecordingsQuery,
    properties: [
        {
            type: PropertyFilterType.Recording,
            key: 'visited_page',
            value: ['/checkout'],
            operator: PropertyOperator.Regex,
        },
        {
            type: PropertyFilterType.Session,
            key: '$entry_current_url',
            value: ['https://example.com/pricing'],
            operator: PropertyOperator.Exact,
        },
    ],
}

const meta: Meta<typeof ReplayFiltersScannerPopover> = {
    title: 'Scenes-App/Replay Vision/ReplayFiltersScannerPopover',
    component: ReplayFiltersScannerPopover,
    decorators: [
        mswDecorator({ get: { '/api/projects/:team_id/vision/quota/': quota } }),
        (Story) => (
            <div className="inline-block rounded border bg-surface-primary p-2">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof ReplayFiltersScannerPopover>

export const WithFilters: Story = {
    args: {
        handoff: {
            searchParams: {},
            query: withFiltersQuery,
            chosenQuery: withFiltersQuery,
            experiment: null,
            pinnedSessionCount: 0,
            droppedCommentSearch: false,
            narrowsSessions: true,
        } satisfies ScannerHandoffFromFilters,
    },
}

export const AllNewRecordings: Story = {
    args: {
        handoff: {
            searchParams: {},
            query: { kind: NodeKind.RecordingsQuery },
            chosenQuery: { kind: NodeKind.RecordingsQuery },
            experiment: null,
            pinnedSessionCount: 3,
            droppedCommentSearch: false,
            narrowsSessions: false,
        } satisfies ScannerHandoffFromFilters,
    },
}
