import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'

import type { Series, TooltipContext } from '@posthog/quill-charts'

import { cohortsModel } from '~/models/cohortsModel'
import type { BreakdownFilter } from '~/queries/schema/schema-general'

import type { FunnelSeriesMeta } from '../shared/funnelSeriesMeta'
import { FunnelLineTooltip } from './FunnelLineTooltip'

// Five-day window matching the mocked date, so the pinned tooltip resolves a stable header.
const DAYS = ['2022-03-08', '2022-03-09', '2022-03-10', '2022-03-11', '2022-03-12']
const DATA_INDEX = 4

// The funnel-trends API returns one conversion series per breakdown value with NO `order`
// field, so `meta.order` is undefined at runtime (despite the `number` type). Constructing
// the meta the same way keeps the story faithful: it exercises FunnelLineTooltip's
// `meta.order ?? …` fallback exactly as production does. A regression that orders series by
// index makes InsightTooltip render `–` for every row except the first.
function funnelSeries(label: string, data: number[], breakdown?: string[]): Series<FunnelSeriesMeta> {
    return {
        key: label,
        label,
        data,
        meta: { days: DAYS, breakdown_value: breakdown, label } as FunnelSeriesMeta,
    }
}

function tooltipContext(
    entries: { series: Series<FunnelSeriesMeta>; value: number; color: string }[]
): TooltipContext<FunnelSeriesMeta> {
    return {
        dataIndex: DATA_INDEX,
        label: DAYS[DATA_INDEX],
        seriesData: entries,
        position: { x: 0, y: 0 },
        hoverPosition: null,
        canvasBounds: new DOMRect(),
        isPinned: true,
        onUnpin: () => {},
    }
}

const BREAKDOWN_FILTER: BreakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }

type Story = StoryObj<typeof FunnelLineTooltip>

const meta: Meta<typeof FunnelLineTooltip> = {
    title: 'Insights/FunnelLineTooltip',
    component: FunnelLineTooltip,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-12',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    render: (props) => {
        useMountedLogic(cohortsModel)
        return <FunnelLineTooltip {...props} />
    },
}
export default meta

// Single conversion series with no breakdown, so the tooltip shows one "Conversion" row.
export const SingleSeries: Story = {
    args: {
        context: tooltipContext([
            { series: funnelSeries('Conversion', [10, 25, 40, 60, 50]), value: 50, color: '#1d4aff' },
        ]),
    },
}

// Regression guard: a broken-down funnel-trends tooltip must show every breakdown's
// conversion percentage. Before the order fix, only the first row showed a value and the
// rest rendered `–`.
export const Breakdown: Story = {
    args: {
        breakdownFilter: BREAKDOWN_FILTER,
        context: tooltipContext([
            { series: funnelSeries('Chrome', [10, 25, 40, 60, 72], ['Chrome']), value: 72, color: '#1d4aff' },
            { series: funnelSeries('Firefox', [5, 12, 20, 30, 48], ['Firefox']), value: 48, color: '#f7a501' },
            { series: funnelSeries('Safari', [2, 6, 14, 22, 31], ['Safari']), value: 31, color: '#42827e' },
            { series: funnelSeries('Edge', [1, 3, 7, 12, 19], ['Edge']), value: 19, color: '#b62b82' },
        ]),
    },
}
