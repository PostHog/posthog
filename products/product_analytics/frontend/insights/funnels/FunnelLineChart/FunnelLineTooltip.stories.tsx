import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'

import type { Series, TooltipContext } from '@posthog/quill-charts'

import { cohortsModel } from '~/models/cohortsModel'
import type { BreakdownFilter } from '~/queries/schema/schema-general'

import type { FunnelSeriesMeta } from '../shared/funnelSeriesMeta'
import { FunnelLineTooltip } from './FunnelLineTooltip'

const days = ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14']
const DATA_INDEX = 2

const breakdownFilter: BreakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }

const COLORS = ['#1d4aff', '#621da6', '#42827e', '#f4a261', '#e76f51']

// Breakdown series are supplied in a deliberately scrambled order (40, 20, 55, 60, 10).
// The tooltip must reorder rows by conversion value descending, so the screenshot reads
// Firefox 60% → Edge 55% → Safari 40% → Chrome 20% → Opera 10% top to bottom.
const breakdownRows: { label: string; value: number }[] = [
    { label: 'Safari', value: 40 },
    { label: 'Chrome', value: 20 },
    { label: 'Edge', value: 55 },
    { label: 'Firefox', value: 60 },
    { label: 'Opera', value: 10 },
]

function buildContext(rows: { label: string; value: number }[]): TooltipContext<FunnelSeriesMeta> {
    const seriesData = rows.map(({ label, value }, idx) => {
        const series: Series<FunnelSeriesMeta> = {
            key: label,
            label,
            data: days.map(() => value),
            meta: { days, breakdown_value: label, order: 0, label },
        }
        return { series, value, color: COLORS[idx % COLORS.length] }
    })
    return {
        dataIndex: DATA_INDEX,
        label: days[DATA_INDEX],
        seriesData,
        position: { x: 0, y: 0 },
        hoverPosition: null,
        canvasBounds: { x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0 } as DOMRect,
        isPinned: true,
        onUnpin: () => {},
    }
}

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/FunnelLineChart/Tooltip',
    component: FunnelLineTooltip,
    parameters: {
        layout: 'centered',
        mockDate: '2024-06-12',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

export const BreakdownOrderedByConversion: Story = {
    render: () => {
        useMountedLogic(cohortsModel)

        return (
            <FunnelLineTooltip
                context={buildContext(breakdownRows)}
                timezone="UTC"
                interval="day"
                breakdownFilter={breakdownFilter}
                groupTypeLabel="persons"
                onRowClick={() => {}}
            />
        )
    },
}
