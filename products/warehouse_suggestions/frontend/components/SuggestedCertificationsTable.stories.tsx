import type { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type { WarehouseSuggestionApi, WarehouseSuggestionStatusApi } from '../generated/api.schemas'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestedCertificationsTable } from './SuggestedCertificationsTable'

const LIST_URL = '/api/projects/:team_id/warehouse_suggestions/'
const STATUS_URL = '/api/projects/:team_id/warehouse_suggestions/status/'

const status: WarehouseSuggestionStatusApi = {
    enabled: true,
    eligible: true,
    days_with_data: 30,
    window_days: 30,
    paused_reason: null,
    refreshed_at: '2026-10-07T08:30:00Z',
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
        evidence_window_start: '2026-09-07T00:00:00Z',
        evidence_window_end: '2026-10-07T00:00:00Z',
        last_seen_at: '2026-10-07T08:30:00Z',
        status: 'proposed',
        surfaced_at: '2026-10-07T08:30:00Z',
        reviewed_by: null,
        reviewed_at: null,
        dismissal_reason: null,
        dismissal_note: null,
        created_asset: null,
        asset_outcome: null,
        realized_seconds_saved_per_month: null,
        realized_bytes_saved_per_month: null,
        can_act: canAct,
    }
}

interface TableStoryProps {
    results: WarehouseSuggestionApi[]
    width?: 'normal' | 'narrow'
    reviewOpen?: boolean
    confirmSuggestionId?: string
}

function TableStory({ results, width, reviewOpen = false, confirmSuggestionId }: TableStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            [LIST_URL]: { count: results.length, results },
            [STATUS_URL]: status,
        },
    })
    const logic = warehouseSuggestionsLogic({ surface: 'catalog' })
    const { stripState } = useValues(logic)
    useEffect(() => {
        if (stripState !== 'active') {
            return
        }
        if (reviewOpen || confirmSuggestionId) {
            logic.actions.openReview()
        }
        if (confirmSuggestionId) {
            logic.actions.openAcceptConfirm(confirmSuggestionId)
        }
    }, [reviewOpen, confirmSuggestionId, stripState, logic])
    return (
        <div className={width === 'narrow' ? 'w-[520px] p-4' : 'w-[1000px] p-4'}>
            <SuggestedCertificationsTable />
        </div>
    )
}

const meta: Meta<typeof TableStory> = {
    title: 'Warehouse suggestions/Suggested certifications',
    component: TableStory,
    parameters: { layout: 'padded', mockDate: '2026-10-07T10:30:00Z' },
}
export default meta

type Story = StoryObj<typeof TableStory>

const dialogSnapshot = (width: number): Story['parameters'] => ({
    layout: 'fullscreen',
    testOptions: { viewport: { width, height: 900 } },
})

export const Banner: Story = {
    args: {
        results: [
            suggestion('1', 'certify', 'saved_query', 'customer_monthly_revenue'),
            suggestion('2', 'certify', 'table', 'stripe_charges'),
            suggestion('3', 'deprecate', 'saved_query', 'old_marketing_rollup', false),
        ],
    },
}

export const ReviewDialog: Story = {
    args: {
        reviewOpen: true,
        results: [
            suggestion('1', 'certify', 'saved_query', 'customer_monthly_revenue'),
            suggestion('2', 'certify', 'table', 'stripe_charges'),
            suggestion('3', 'deprecate', 'saved_query', 'old_marketing_rollup', false),
        ],
    },
    parameters: dialogSnapshot(1300),
}

export const ReviewDialogNarrow: Story = {
    args: {
        width: 'narrow',
        reviewOpen: true,
        results: [
            suggestion('1', 'certify', 'saved_query', 'customer_monthly_revenue_by_region_and_plan'),
            suggestion('3', 'deprecate', 'saved_query', 'old_marketing_rollup'),
        ],
    },
    parameters: dialogSnapshot(520),
}

export const DeprecateDialog: Story = {
    args: {
        confirmSuggestionId: '3',
        results: [suggestion('3', 'deprecate', 'saved_query', 'old_marketing_rollup')],
    },
    parameters: dialogSnapshot(1300),
}
