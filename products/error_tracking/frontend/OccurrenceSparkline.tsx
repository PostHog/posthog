import { useValues } from 'kea'
import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { useCallback, useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DateRange } from '~/queries/schema/schema-general'

import { SparklineData, SparklineOptions } from './components/SparklineChart/SparklineChart'
import { useDefaultSparklineColorVars, useSparklineOptions } from './hooks/use-sparkline-options'
import { generateSparklineLabels } from './utils'

export function OccurrenceSparkline({
    data,
    className,
    displayXAxis = false,
}: {
    data: SparklineData
    className?: string
    displayXAxis?: boolean
    loading?: boolean
}): JSX.Element {
    const colorVars = useDefaultSparklineColorVars()
    const options = useSparklineOptions({
        backgroundColor: colorVars[0],
        hoverBackgroundColor: colorVars[1],
    })
    const [occurrences, labels, labelRenderer] = useMemo(() => {
        return [
            wrapDataWithColor(data, options),
            data.map((value) => dayjs(value.date).toISOString()),
            (label: string) => {
                return dayjs(label).format('D MMM YYYY HH:mm (UTC)')
            },
        ]
    }, [data, options])

    const withXScale = useCallback((scale: AnyScaleOptions) => {
        return {
            ...scale,
            type: 'timeseries',
            ticks: {
                display: true,
                maxRotation: 0,
                maxTicksLimit: 5,
                font: {
                    size: 10,
                    lineHeight: 1,
                },
            },
            time: {
                unit: 'day',
                displayFormats: {
                    day: 'D MMM',
                },
            },
        } as AnyScaleOptions
    }, [])

    return (
        <Sparkline
            className={className}
            data={occurrences}
            labels={labels}
            renderLabel={labelRenderer}
            withXScale={displayXAxis ? withXScale : undefined}
        />
    )
}

export function useSparklineColors(): { color: string; hoverColor: string } {
    const { isDarkModeOn } = useValues(themeLogic)

    return useMemo(() => {
        return {
            color: isDarkModeOn ? 'primitive-neutral-600' : 'primitive-neutral-200',
            hoverColor: isDarkModeOn ? 'primitive-neutral-200' : 'primitive-neutral-700',
        }
    }, [isDarkModeOn])
}

export function useSparklineData(
    resolution: number,
    dateRange: DateRange,
    values?: number[]
): { values: number[]; labels: string[] } {
    const result = useMemo(() => {
        const labels = generateSparklineLabels(dateRange, resolution).map((label) => label.toISOString())
        if (!values) {
            return { values: new Array(resolution).fill(0), labels }
        }
        return { values, labels }
    }, [values, dateRange, resolution])
    return result
}

function wrapDataWithColor(data: SparklineData, options: SparklineOptions): any[] {
    return [
        {
            values: data.map((d) => d.value),
            name: 'Occurrences',
            color: options.backgroundColor,
            hoverColor: options.hoverBackgroundColor,
        },
    ]
}
