import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { dayjs } from 'lib/dayjs'

import { useStorybookMocks } from '~/mocks/browser'

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
    refreshed_at: dayjs().subtract(2, 'hour').toISOString(),
}

function materialize(id: string, name: string, savedSeconds: number, canAct = true): WarehouseSuggestionApi {
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
            unknown_sources: { names: [], hidden_count: 1 },
        },
        payload_version: 1,
        evidence: {
            human_requests: 214,
            human_users: 6,
            human_days: 27,
            requests_by_surface: { sql_editor: 120, dashboard: 60, api: 34 },
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

const suggestions = [
    materialize('1', 'customer_monthly_revenue', 1080),
    materialize('2', 'sessions_by_plan_daily', 2400),
    materialize('3', 'stripe_invoices_enriched', 0),
]

interface StripStoryProps {
    results?: WarehouseSuggestionApi[]
    statusOverrides?: Partial<WarehouseSuggestionStatusApi>
    expanded?: boolean
    failing?: boolean
    width?: 'normal' | 'narrow'
}

function StripStory({
    results = suggestions,
    statusOverrides,
    expanded = true,
    failing,
    width,
}: StripStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            [LIST_URL]: () => (failing ? [500, { detail: 'Server error' }] : { count: results.length, results }),
            [STATUS_URL]: { ...status, ...statusOverrides },
        },
    })
    useEffect(() => {
        warehouseSuggestionsLogic({ surface: 'models' }).actions.setCollapsed(!expanded)
    }, [expanded])

    return (
        <div className={width === 'narrow' ? 'w-[520px] p-4' : 'w-[1000px] p-4'}>
            <SuggestedModelsStrip />
        </div>
    )
}

const meta: Meta<typeof StripStory> = {
    title: 'Warehouse suggestions/Suggested models strip',
    component: StripStory,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof StripStory>

export const Expanded: Story = {}

export const Collapsed: Story = { args: { expanded: false } }

export const ExpandedNarrow: Story = { args: { width: 'narrow' } }

export const ViewerWithoutEditAccess: Story = {
    args: { results: [materialize('1', 'customer_monthly_revenue', 1080, false)] },
}

export const WarmingUp: Story = { args: { results: [], statusOverrides: { days_with_data: 12 } } }

export const NotEligible: Story = { args: { results: [], statusOverrides: { eligible: false } } }

export const LoadFailed: Story = { args: { failing: true } }
