import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { useStorybookMocks } from '~/mocks/browser'

import type { WarehouseSuggestionApi, WarehouseSuggestionStatusApi } from '../generated/api.schemas'
import { SuggestedCertificationsTable } from './SuggestedCertificationsTable'

const LIST_URL = '/api/projects/:team_id/warehouse_suggestions/'
const STATUS_URL = '/api/projects/:team_id/warehouse_suggestions/status/'

const status: WarehouseSuggestionStatusApi = {
    enabled: true,
    eligible: true,
    days_with_data: 30,
    window_days: 30,
    paused_reason: null,
    refreshed_at: dayjs().subtract(2, 'hour').toISOString(),
}

function suggestion(
    id: string,
    kind: 'certify' | 'deprecate',
    subjectKind: 'saved_query' | 'table',
    name: string,
    canAct = true
): WarehouseSuggestionApi {
    return {
        id,
        kind,
        subject_kind: subjectKind,
        subject_id: `subject-${id}`,
        payload:
            kind === 'certify'
                ? { subject_name: name }
                : { subject_name: name, refresh_seconds_per_month: 5400, refresh_bytes_per_month: 2 * 10 ** 12 },
        payload_version: 1,
        evidence: {
            human_requests: kind === 'certify' ? 640 : 0,
            human_users: kind === 'certify' ? 9 : 0,
            human_days: kind === 'certify' ? 28 : 0,
            requests_by_surface: kind === 'certify' ? { dashboard: 400, mcp: 240 } : {},
        },
        evidence_window_start: dayjs().subtract(30, 'day').toISOString(),
        evidence_window_end: dayjs().toISOString(),
        last_seen_at: dayjs().subtract(2, 'hour').toISOString(),
        score: 2,
        status: 'proposed',
        surfaced_at: dayjs().subtract(2, 'hour').toISOString(),
        reviewed_by: null,
        reviewed_at: null,
        dismissal_reason: null,
        dismissal_note: null,
        created_asset: null,
        asset_outcome: null,
        can_act: canAct,
    }
}

interface TableStoryProps {
    results: WarehouseSuggestionApi[]
}

function TableStory({ results }: TableStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            [LIST_URL]: { count: results.length, results },
            [STATUS_URL]: status,
        },
    })
    return (
        <div className="w-[1000px] p-4">
            <SuggestedCertificationsTable />
        </div>
    )
}

const meta: Meta<typeof TableStory> = {
    title: 'Warehouse suggestions/Suggested certifications',
    component: TableStory,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof TableStory>

export const CertifyAndDeprecate: Story = {
    args: {
        results: [
            suggestion('1', 'certify', 'saved_query', 'customer_monthly_revenue'),
            suggestion('2', 'certify', 'table', 'stripe_charges'),
            suggestion('3', 'deprecate', 'saved_query', 'old_marketing_rollup', false),
        ],
    },
}
