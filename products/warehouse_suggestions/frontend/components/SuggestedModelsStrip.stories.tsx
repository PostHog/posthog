import type { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import { DataModelingSyncInterval } from '~/types'

import type { WarehouseSuggestionApi, WarehouseSuggestionStatusApi } from '../generated/api.schemas'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestedModelsStrip } from './SuggestedModelsStrip'

const LIST_URL = '/api/projects/:team_id/warehouse_suggestions/'
const SAVED_QUERY_URL = '/api/projects/:team_id/warehouse_saved_queries/:id/'
const CHECK_INCREMENTAL_URL = '/api/projects/:team_id/warehouse_saved_queries/check_incremental/'
const STATUS_URL = '/api/projects/:team_id/warehouse_suggestions/status/'

const status: WarehouseSuggestionStatusApi = {
    enabled: true,
    eligible: true,
    days_with_data: 30,
    window_days: 30,
    paused_reason: null,
    refreshed_at: '2026-10-07T08:30:00Z',
}

interface MaterializeOptions {
    canAct?: boolean
    unknownSources?: boolean
    incremental?: boolean
}

function materialize(
    id: string,
    name: string,
    savedSeconds: number,
    { canAct = true, unknownSources = false, incremental = false }: MaterializeOptions = {}
): WarehouseSuggestionApi {
    return {
        id,
        kind: 'materialize',
        subject_kind: 'saved_query',
        subject_id: `view-${id}`,
        payload: {
            subject_name: name,
            refresh_interval_seconds: 86400,
            saves_seconds_per_month: savedSeconds,
            saves_bytes_per_month: 3 * 10 ** 12,
            freshness_today_seconds: 3600,
            freshness_after_seconds: 90000,
            live_sources: { names: ['events'], hidden_count: 0 },
            unknown_sources: { names: [], hidden_count: unknownSources ? 1 : 0 },
            refresh_interval_basis: 'source_sync',
            ...(incremental
                ? {
                      refresh_mode: 'incremental',
                      incremental_key: 'day',
                      unique_key: ['day', 'plan'],
                      lookback_seconds: 3600,
                  }
                : { refresh_mode: 'full' }),
        },
        payload_version: 1,
        evidence: {
            human_requests: 214,
            human_users: 6,
            human_days: 27,
            requests_by_surface: { sql_editor: 120, dashboard: 60, api: 34 },
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

function unmaterialize(id: string, name: string): WarehouseSuggestionApi {
    const base = materialize(id, name, 0)
    return {
        ...base,
        kind: 'unmaterialize',
        payload: {
            subject_name: name,
            refresh_seconds_per_month: 5400,
            refresh_bytes_per_month: 4 * 10 ** 12,
            live_seconds_per_month: 900,
            live_bytes_per_month: 10 ** 12,
            read_seconds: 3.6,
        },
        evidence: { human_requests: 9, human_users: 2, human_days: 6, requests_by_surface: { sql_editor: 9 } },
    }
}

const suggestions = [
    materialize('1', 'customer_monthly_revenue', 1080),
    materialize('2', 'sessions_by_plan_daily', 2400),
    materialize('3', 'stripe_invoices_enriched', 0, { unknownSources: true }),
    unmaterialize('4', 'legacy_signup_funnel'),
]

const manySuggestions = Array.from({ length: 7 }, (_, index) =>
    materialize(`${index + 1}`, `product_usage_rollup_${index + 1}`, 600 * (index + 1))
)

interface StripStoryProps {
    results?: WarehouseSuggestionApi[]
    statusOverrides?: Partial<WarehouseSuggestionStatusApi>
    reviewOpen?: boolean
    failing?: boolean
    width?: 'normal' | 'narrow'
    openDialogWithInterval?: DataModelingSyncInterval
    confirmSuggestionId?: string
}

function StripStory({
    results = suggestions,
    statusOverrides,
    reviewOpen = false,
    failing,
    width,
    openDialogWithInterval,
    confirmSuggestionId,
}: StripStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            [LIST_URL]: () => (failing ? [500, { detail: 'Server error' }] : { count: results.length, results }),
            [STATUS_URL]: { ...status, ...statusOverrides },
            [SAVED_QUERY_URL]: {
                id: 'view-1',
                query: { kind: 'HogQLQuery', query: 'SELECT day, plan, count() FROM events GROUP BY day, plan' },
            },
        },
        post: {
            [CHECK_INCREMENTAL_URL]: {
                eligible: true,
                key_candidates: ['day'],
                unique_key_candidates: ['day', 'plan'],
                key_candidate_types: { day: 'date', plan: 'string' },
                blockers: [],
                warnings: [],
            },
        },
    })
    const logic = warehouseSuggestionsLogic({ surface: 'models' })
    const { stripState } = useValues(logic)
    useEffect(() => {
        if (stripState !== 'active') {
            return
        }
        if (reviewOpen || openDialogWithInterval || confirmSuggestionId) {
            logic.actions.openReview()
        }
        if (confirmSuggestionId) {
            logic.actions.openAcceptConfirm(confirmSuggestionId)
        }
        if (!openDialogWithInterval) {
            return
        }
        logic.actions.openMaterializeModal(results[0].id)
        logic.actions.setMaterializeInterval(openDialogWithInterval)
    }, [reviewOpen, openDialogWithInterval, confirmSuggestionId, stripState, logic, results])

    return (
        <div className={width === 'narrow' ? 'w-[520px] p-4' : 'w-[1000px] p-4'}>
            <SuggestedModelsStrip />
        </div>
    )
}

const meta: Meta<typeof StripStory> = {
    title: 'Warehouse suggestions/Suggested models strip',
    component: StripStory,
    parameters: { layout: 'padded', mockDate: '2026-10-07T10:30:00Z' },
}
export default meta

type Story = StoryObj<typeof StripStory>

const DIALOG_SNAPSHOT: Story['parameters'] = {
    layout: 'fullscreen',
    testOptions: { viewport: { width: 1300, height: 900 } },
}

export const Banner: Story = {}

export const BannerNarrow: Story = { args: { width: 'narrow' } }

export const ReviewDialog: Story = { args: { reviewOpen: true }, parameters: DIALOG_SNAPSHOT }

export const ReviewDialogViewerWithoutEditAccess: Story = {
    args: { reviewOpen: true, results: [materialize('1', 'customer_monthly_revenue', 1080, { canAct: false })] },
    parameters: DIALOG_SNAPSHOT,
}

export const WarmingUp: Story = { args: { results: [], statusOverrides: { days_with_data: 12 } } }

export const NotEligible: Story = { args: { results: [], statusOverrides: { eligible: false } } }

export const LoadFailed: Story = { args: { failing: true } }

export const ReviewDialogManySuggestions: Story = {
    args: { reviewOpen: true, results: manySuggestions },
    parameters: DIALOG_SNAPSHOT,
}

export const MaterializeDialogLongerScheduleUnknownSources: Story = {
    args: {
        results: [materialize('3', 'stripe_invoices_enriched', 1080, { unknownSources: true })],
        openDialogWithInterval: '7day',
    },
    parameters: DIALOG_SNAPSHOT,
}

export const MaterializeDialogIncrementalProposal: Story = {
    args: {
        results: [materialize('1', 'sessions_by_plan_daily', 2400, { incremental: true })],
        openDialogWithInterval: '24hour',
    },
    parameters: DIALOG_SNAPSHOT,
}

export const StopMaterializingDialog: Story = {
    args: { confirmSuggestionId: '4' },
    parameters: DIALOG_SNAPSHOT,
}
