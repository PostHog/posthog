import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'

import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { cohortsModel } from '~/models/cohortsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import { InsightTooltip } from './InsightTooltip'
import { InsightTooltipProps } from './insightTooltipUtils'

const data = {
    date: '2022-08-31',
    timezone: 'UTC',
    seriesData: [
        {
            id: 0,
            dataIndex: 7,
            datasetIndex: 2,
            dotted: true,
            series: {
                order: 0,
                node: {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    custom_name: 'Pageview of people with very long names like this text',
                },
                math: {
                    math: 'dau',
                },
            },
            label: '$pageview',
            color: '#1d4aff',
            count: 1,
        },
        {
            id: 1,
            dataIndex: 7,
            datasetIndex: 3,
            dotted: true,
            series: {
                order: 1,
                node: {
                    kind: NodeKind.EventsNode,
                    event: 'filter added',
                    name: 'filter added',
                },
                math: {},
            },
            label: 'filter added',
            color: '#621da6',
            count: 1,
        },
    ],
}

type Story = StoryObj<InsightTooltipProps>
const meta: Meta<InsightTooltipProps> = {
    title: 'Components/InsightTooltip',
    component: InsightTooltip,
    args: {
        date: data.date,
        timezone: data.timezone,
        seriesData: data.seriesData as any,
        hideColorCol: false,
        renderCount: (value: number): string => `${value}`,
        renderSeries: (value) => value,
        groupTypeLabel: 'people',
    },
    render: (props) => {
        useMountedLogic(cohortsModel)

        return <InsightTooltip {...props} />
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const Columns: Story = {
    args: {
        seriesData: [
            {
                id: 0,
                dataIndex: 3,
                datasetIndex: 2,
                order: 1,
                dotted: false,
                breakdown_value: 'Safari',
                series: {
                    order: 1,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$autocapture',
                        name: '$autocapture',
                    },
                    math: {
                        math: BaseMathType.TotalCount,
                    },
                },
                label: '$autocapture - Safari',
                color: '#42827e',
                count: 0,
            },
            {
                id: 1,
                dataIndex: 3,
                datasetIndex: 0,
                order: 0,
                dotted: false,
                breakdown_value: 'Chrome',
                series: {
                    order: 0,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        custom_name: 'Pageview of people with very long names like this text',
                    },
                    math: {
                        math: BaseMathType.TotalCount,
                    },
                },
                label: '$pageview - Chrome',
                color: '#1d4aff',
                count: 0,
            },
            {
                id: 2,
                dataIndex: 3,
                datasetIndex: 1,
                order: 0,
                dotted: false,
                breakdown_value: 'Safari',
                series: {
                    order: 0,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        custom_name: 'Pageview of people with very long names like this text',
                    },
                    math: {
                        math: BaseMathType.TotalCount,
                    },
                },
                label: '$pageview - Safari',
                color: '#621da6',
                count: 0,
            },
        ],
    },
}

const longBreakdownValue =
    'https://www.example.com/some/really/long/breakdown/value/that/keeps/going/and/going?utm_source=newsletter'
const anotherLongBreakdownValue =
    'https://www.example.com/another/extremely/long/path/segment/that/should/be/clipped/with/an/ellipsis'

// Demonstrates that long breakdown values (first column) and long series/event
// names (column headers) clip with an ellipsis instead of forcing the tooltip
// wide enough to need horizontal scrolling.
export const LongNames: Story = {
    args: {
        seriesData: [
            {
                id: 0,
                dataIndex: 3,
                datasetIndex: 0,
                order: 0,
                dotted: false,
                breakdown_value: longBreakdownValue,
                series: {
                    order: 0,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        custom_name: 'Pageview of people with extremely long custom names that go on and on and on',
                    },
                    math: {
                        math: BaseMathType.TotalCount,
                    },
                },
                label: '$pageview - long',
                color: '#1d4aff',
                count: 1234,
            },
            {
                id: 1,
                dataIndex: 3,
                datasetIndex: 1,
                order: 1,
                dotted: false,
                breakdown_value: longBreakdownValue,
                series: {
                    order: 1,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: 'some_event_with_an_extremely_long_machine_readable_name_that_keeps_going',
                        name: 'some_event_with_an_extremely_long_machine_readable_name_that_keeps_going',
                    },
                    math: {
                        math: BaseMathType.TotalCount,
                    },
                },
                label: 'some_event_with_an_extremely_long_machine_readable_name_that_keeps_going',
                color: '#621da6',
                count: 56,
            },
            {
                id: 2,
                dataIndex: 3,
                datasetIndex: 0,
                order: 0,
                dotted: false,
                breakdown_value: anotherLongBreakdownValue,
                series: {
                    order: 0,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        custom_name: 'Pageview of people with extremely long custom names that go on and on and on',
                    },
                    math: {
                        math: BaseMathType.TotalCount,
                    },
                },
                label: '$pageview - long',
                color: '#1d4aff',
                count: 789,
            },
            {
                id: 3,
                dataIndex: 3,
                datasetIndex: 1,
                order: 1,
                dotted: false,
                breakdown_value: anotherLongBreakdownValue,
                series: {
                    order: 1,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: 'some_event_with_an_extremely_long_machine_readable_name_that_keeps_going',
                        name: 'some_event_with_an_extremely_long_machine_readable_name_that_keeps_going',
                    },
                    math: {
                        math: BaseMathType.TotalCount,
                    },
                },
                label: 'some_event_with_an_extremely_long_machine_readable_name_that_keeps_going',
                color: '#621da6',
                count: 4,
            },
        ] as any,
    },
}

// Math tags ("Average of <property>") are white-space:nowrap; without bounding
// they force the column wider and the badge bleeds into the neighbouring column.
// This exercises the column-per-entity layout so the badge stays clipped to its
// column with the long property truncated.
export const MathTags: Story = {
    args: {
        seriesData: [
            {
                id: 0,
                dataIndex: 3,
                datasetIndex: 0,
                order: 0,
                dotted: false,
                breakdown_value: 'Chrome',
                series: {
                    order: 0,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                    },
                    math: {
                        math: 'avg',
                        math_property: 'a_really_long_numeric_property_name_that_overflows',
                    },
                },
                label: '$pageview - Chrome',
                color: '#1d4aff',
                count: 1234,
            },
            {
                id: 1,
                dataIndex: 3,
                datasetIndex: 1,
                order: 1,
                dotted: false,
                breakdown_value: 'Safari',
                series: {
                    order: 1,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                    },
                    math: {
                        math: 'avg',
                        math_property: 'a_really_long_numeric_property_name_that_overflows',
                    },
                },
                label: '$pageview - Safari',
                color: '#621da6',
                count: 56,
            },
        ] as any,
    },
}

// Same math badge, but in the series-as-rows layout (no breakdown/compare), which
// renders in a fixed-width label column. The math label word ("Average") must stay
// fully visible; only the long property part may truncate.
export const MathTagsAsRows: Story = {
    args: {
        seriesData: [
            {
                id: 0,
                dataIndex: 3,
                datasetIndex: 0,
                order: 0,
                dotted: false,
                series: {
                    order: 0,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        custom_name: 'A really long series name that needs to be truncated',
                    },
                    math: {
                        math: 'avg',
                        math_property: 'a_really_long_numeric_property_name_that_overflows',
                    },
                },
                label: '$pageview',
                color: '#1d4aff',
                count: 468,
            },
            {
                id: 1,
                dataIndex: 3,
                datasetIndex: 1,
                order: 1,
                dotted: false,
                series: {
                    order: 1,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        custom_name: 'Another long series name that should also be truncated',
                    },
                    math: {
                        math: 'avg',
                        math_property: 'amount',
                    },
                },
                label: '$pageview',
                color: '#621da6',
                count: 0,
            },
        ] as any,
    },
}

// Single series in the rows layout (one row, "Click to view people"). The label
// cell holds the icon, the truncated series name, and the "Average of <property>"
// badge; the value sits in its own column. The math label word must stay whole and
// must not collide with the property text.
export const MathTagsSingleSeries: Story = {
    args: {
        seriesData: [
            {
                id: 0,
                dataIndex: 3,
                datasetIndex: 0,
                order: 0,
                dotted: false,
                series: {
                    order: 0,
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        custom_name: 'Avg widgets per dashboard over the whole period',
                    },
                    math: {
                        math: 'avg',
                        math_property: 'dashboard_widget_count_property',
                    },
                },
                label: '$pageview',
                color: '#1d4aff',
                count: 1.54,
            },
        ] as any,
    },
}

export function InWrapper(): JSX.Element {
    useMountedLogic(cohortsModel)

    return (
        <div className="min-h-50">
            <div className="InsightTooltipWrapper">
                <InsightTooltip
                    date={data.date}
                    timezone={data.timezone}
                    seriesData={data.seriesData as any}
                    renderCount={(value: number): string => humanFriendlyNumber(value)}
                    renderSeries={(value, datum) => {
                        const hasBreakdown = datum.breakdown_value !== undefined && !!datum.breakdown_value
                        return (
                            <div className="datum-label-column">
                                <SeriesLetter
                                    className="mr-2"
                                    hasBreakdown={hasBreakdown}
                                    seriesIndex={datum?.series?.order ?? datum.id}
                                    seriesColor={datum.color}
                                />
                                {value}
                            </div>
                        )
                    }}
                    groupTypeLabel="people"
                />
            </div>
        </div>
    )
}
// FIXME: InWrapper fails at locator.screenshot(), so it's skipped from visual regression
InWrapper.tags = ['test-skip']
