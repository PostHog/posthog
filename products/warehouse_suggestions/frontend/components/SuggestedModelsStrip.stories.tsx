import type { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import { DataModelingSyncInterval } from '~/types'

import type { WarehouseSuggestionApi, WarehouseSuggestionStatusApi } from '../generated/api.schemas'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestedModelsStrip } from './SuggestedModelsStrip'

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

interface MaterializeOptions {
    canAct?: boolean
    unknownSources?: boolean
}

function materialize(
    id: string,
    name: string,
    savedSeconds: number,
    { canAct = true, unknownSources = false }: MaterializeOptions = {}
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
        can_act: canAct,
    }
}

const suggestions = [
    materialize('1', 'customer_monthly_revenue', 1080),
    materialize('2', 'sessions_by_plan_daily', 2400),
    materialize('3', 'stripe_invoices_enriched', 0, { unknownSources: true }),
]

const manySuggestions = Array.from({ length: 7 }, (_, index) =>
    materialize(`${index + 1}`, `product_usage_rollup_${index + 1}`, 600 * (index + 1))
)

interface StripStoryProps {
    results?: WarehouseSuggestionApi[]
    statusOverrides?: Partial<WarehouseSuggestionStatusApi>
    expanded?: boolean
    failing?: boolean
    width?: 'normal' | 'narrow'
    openDialogWithInterval?: DataModelingSyncInterval
}

function StripStory({
    results = suggestions,
    statusOverrides,
    expanded = true,
    failing,
    width,
    openDialogWithInterval,
}: StripStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            [LIST_URL]: () => (failing ? [500, { detail: 'Server error' }] : { count: results.length, results }),
            [STATUS_URL]: { ...status, ...statusOverrides },
        },
    })
    const logic = warehouseSuggestionsLogic({ surface: 'models' })
    const { stripState } = useValues(logic)
    useEffect(() => {
        logic.actions.setCollapsed(!expanded)
    }, [expanded, logic])
    useEffect(() => {
        if (!openDialogWithInterval || stripState !== 'active') {
            return
        }
        logic.actions.openMaterializeModal(results[0].id)
        logic.actions.setMaterializeInterval(openDialogWithInterval)
    }, [openDialogWithInterval, stripState, logic, results])

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

export const Expanded: Story = {}

export const Collapsed: Story = { args: { expanded: false } }

export const ExpandedNarrow: Story = { args: { width: 'narrow' } }

export const ViewerWithoutEditAccess: Story = {
    args: { results: [materialize('1', 'customer_monthly_revenue', 1080, { canAct: false })] },
}

export const WarmingUp: Story = { args: { results: [], statusOverrides: { days_with_data: 12 } } }

export const NotEligible: Story = { args: { results: [], statusOverrides: { eligible: false } } }

export const LoadFailed: Story = { args: { failing: true } }

export const ManySuggestions: Story = { args: { results: manySuggestions } }

export const MaterializeDialogLongerScheduleUnknownSources: Story = {
    args: {
        results: [materialize('3', 'stripe_invoices_enriched', 1080, { unknownSources: true })],
        openDialogWithInterval: '7day',
    },
}
