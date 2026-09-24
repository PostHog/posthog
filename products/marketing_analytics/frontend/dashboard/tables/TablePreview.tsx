import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'
import { TileId } from 'scenes/web-analytics/common'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { MarketingBreakdownTable } from './MarketingBreakdownTable'
import { TablePreviewState, tablePreviewLogic } from './tablePreviewLogic'
import {
    BOUNCE_RATE_COLUMN,
    PAGES_PER_SESSION_COLUMN,
    SESSIONS_COLUMN,
    SESSION_DURATION_COLUMN,
} from './webStatsColumns'
import { WebStatsRow } from './webStatsRows'

const rows: WebStatsRow[] = [
    {
        breakdownValue: 'Direct',
        sessions: [120, 100],
        views: [240, 180],
        session_duration: [90, 60],
        bounce_rate: [0.3, 0.4],
    },
    {
        breakdownValue: 'Paid search',
        sessions: [80, 100],
        views: [160, 200],
        session_duration: [45, 60],
        bounce_rate: [0.4, 0.3],
    },
    {
        breakdownValue: 'Email',
        sessions: [20, 10],
        views: [60, 20],
        session_duration: [120, 90],
        bounce_rate: [0.2, 0.25],
    },
    { breakdownValue: '', sessions: [0, null], views: [0, null], session_duration: [0, null], bounce_rate: [0, null] },
    { breakdownValue: BREAKDOWN_OTHER_STRING_LABEL, sessions: [5, 4], views: [10, 8], bounce_rate: [0.5, 0.5] },
]

export function TablePreview({
    initialState = 'loaded',
    initiallyCompare = false,
}: {
    initialState?: TablePreviewState
    initiallyCompare?: boolean
}): JSX.Element {
    const previewKey = useId()
    const logic = tablePreviewLogic({ previewKey, initialState, initiallyCompare })
    const { state, compare, focusedValue } = useValues(logic)
    const { setState, setCompare, setFocusedValue } = useActions(logic)

    return (
        <div className="flex flex-col gap-4">
            <MarketingBreakdownTable
                tileId={TileId.MARKETING}
                titlePrefix="Engagement by"
                breakdownLabel="Channel"
                rows={state === 'empty' ? [] : rows}
                rowKey={(row) => row.breakdownValue}
                breakdownValue={(row) => row.breakdownValue}
                columns={[SESSIONS_COLUMN, SESSION_DURATION_COLUMN, BOUNCE_RATE_COLUMN, PAGES_PER_SESSION_COLUMN]}
                defaultSortKey="sessions"
                compare={compare}
                currency={CurrencyCode.USD}
                loading={state === 'loading'}
                error={state === 'error'}
                onRetry={() => setState('loading')}
                emptyState="No sessions in this date range. Try a wider date range."
                footnote="Grouped by session entry. Visitors can appear in more than one row."
                exportFilename="marketing-engagement"
                focusedBreakdownValue={focusedValue}
                onFocusBreakdown={setFocusedValue}
            />
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton data-attr="marketing-breakdown-story-show-loading" onClick={() => setState('loading')}>
                    Show loading
                </LemonButton>
                <LemonButton data-attr="marketing-breakdown-story-show-data" onClick={() => setState('loaded')}>
                    Show data
                </LemonButton>
                <LemonButton data-attr="marketing-breakdown-story-show-empty" onClick={() => setState('empty')}>
                    Show empty
                </LemonButton>
                <LemonButton data-attr="marketing-breakdown-story-show-error" onClick={() => setState('error')}>
                    Show error
                </LemonButton>
                <LemonSwitch
                    data-attr="marketing-breakdown-story-compare"
                    checked={compare}
                    onChange={setCompare}
                    label="Compare"
                />
            </div>
        </div>
    )
}
