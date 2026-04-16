import { Meta, StoryObj } from '@storybook/react'
import * as d3 from 'd3'

import { dayjs } from 'lib/dayjs'

import type { SparklineData, SparklineEvent } from './types'
import { VolumeSparkline, VolumeSparklineProps } from './VolumeSparkline'

const STORY_KEY = 'storybook-volume-sparkline'

const meta: Meta<VolumeSparklineProps> = {
    title: 'ErrorTracking/VolumeSparkline',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    component: VolumeSparkline,
    args: {
        sparklineKey: STORY_KEY,
    },
}

export default meta

type Story = StoryObj<VolumeSparklineProps>

const resolution = 60

export const DetailedFullAxisWithEvents: Story = {
    args: {
        data: buildData(),
        layout: 'detailed',
        xAxis: 'full',
        events: buildEvents('2022-01-05', '2022-01-10'),
        className: 'w-[800px] h-[200px]',
    },
}

export const DetailedOverlappingEventDates: Story = {
    args: {
        data: buildData(),
        layout: 'detailed',
        xAxis: 'full',
        events: buildEvents('2022-01-05', '2022-01-05'),
        className: 'w-[800px] h-[200px]',
    },
}

export const DetailedMostlyZeros: Story = {
    args: {
        data: buildData(0, 0),
        layout: 'detailed',
        xAxis: 'full',
        className: 'w-[800px] h-[200px]',
    },
}

export const DetailedZerosAndOnes: Story = {
    args: {
        data: buildData(0, 1),
        layout: 'detailed',
        xAxis: 'full',
        className: 'w-[800px] h-[200px]',
    },
}

export const EventsBeforeDataRange: Story = {
    args: {
        data: buildData(0, 1000, '2022-02-01', '2022-03-01'),
        layout: 'detailed',
        xAxis: 'full',
        events: buildEvents('2022-01-01', '2022-01-02'),
        className: 'w-[800px] h-[200px]',
    },
}

export const CompactIssuesList: Story = {
    args: {
        data: buildData(),
        layout: 'compact',
        xAxis: 'minimal',
        className: 'w-[200px] h-10',
    },
}

function buildData(
    minValue: number = 0,
    maxValue: number = 1000,
    minDate: string = '2022-01-01',
    maxDate: string = '2022-02-01'
): SparklineData {
    const generator = d3.randomLcg(42)
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

function buildEvents(firstDate: string, lastDate: string): SparklineEvent<string>[] {
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
