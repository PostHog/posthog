import { action } from '@storybook/addon-actions'
import { Meta, StoryObj } from '@storybook/react'
import * as d3 from 'd3'

import { dayjs } from 'lib/dayjs'

import { SparklineChart, SparklineEvent, SparklineOptions } from './SparklineChart'

const meta: Meta = {
    title: 'ErrorTracking/SparklineChart',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    component: SparklineChart,
}

export default meta

type Story = StoryObj<typeof SparklineChart>

const resolution = 60

const datumInteractions = {
    onDatumMouseEnter: action('datum-mouse-enter'),
    onDatumMouseLeave: action('datum-mouse-leave'),
}

const eventsInteractions = {
    onEventMouseEnter: action('mouse-enter-event'),
    onEventMouseLeave: action('mouse-leave-event'),
    onEventClick: action('mouse-click-event'),
}

export const IssueChartInsideRange: Story = {
    args: {
        data: buildData(),
        events: buildEvents('2022-01-05', '2022-01-10'),
        options: buildSparklineOptions(),
        className: 'w-[800px] h-[200px]',
    },
}

export const IssueChartWithZeroes: Story = {
    args: {
        data: buildData(0, 0),
        options: buildSparklineOptions(),
        className: 'w-[800px] h-[200px]',
    },
}

export const IssueChartWithZeroesAndOnes: Story = {
    args: {
        data: buildData(0, 1),
        options: buildSparklineOptions(),
        className: 'w-[800px] h-[200px]',
    },
}

export const IssueChartWithOverlappingEvents: Story = {
    args: {
        data: buildData(),
        events: buildEvents('2022-01-05', '2022-01-05'),
        options: buildSparklineOptions(),
        className: 'w-[800px] h-[200px]',
    },
}

export const IssueChartWithBeforeEvents: Story = {
    args: {
        data: buildData(0, 1000, '2022-02-01', '2022-03-01'),
        events: buildEvents('2022-01-01', '2022-01-02'),
        options: buildSparklineOptions(),
        className: 'w-[800px] h-[200px]',
    },
}

// Data builders
function buildData(
    minValue: number = 0,
    maxValue: number = 1000,
    minDate: string = '2022-01-01',
    maxDate: string = '2022-02-01'
): Array<{ value: number; date: Date }> {
    const generator = d3.randomLcg(42) // Initialize a random generator with seed
    const dayJsStart = dayjs(minDate)
    const dayJsEnd = dayjs(maxDate)
    const binSize = dayJsEnd.diff(dayJsStart, 'seconds') / resolution
    return new Array(resolution).fill(0).map((_, index) => {
        return {
            value: Math.round(generator() * (maxValue - minValue) + minValue),
            date: dayJsStart.add(index * binSize, 'seconds').toDate(),
        }
    })
}

function buildSparklineOptions(): SparklineOptions {
    return {
        ...datumInteractions,
        ...eventsInteractions,
        backgroundColor: 'var(--color-neutral-200)',
        hoverBackgroundColor: 'var(--color-neutral-700)',
        axisColor: 'var(--color-neutral-300)',
        eventLabelHeight: 20,
        eventMinSpace: 2,
        eventLabelPaddingX: 5,
        eventLabelPaddingY: 3,
        borderRadius: 5,
        minBarHeight: 10,
    }
}

function buildEvents(firstDate: string, lastDate: string): Array<SparklineEvent<string>> {
    return [
        {
            id: '1',
            date: new Date(firstDate),
            payload: 'First seen',
            color: 'var(--brand-red)',
        },
        {
            id: '2',
            date: new Date(lastDate),
            payload: 'Last seen',
            color: 'var(--brand-blue)',
        },
    ]
}
