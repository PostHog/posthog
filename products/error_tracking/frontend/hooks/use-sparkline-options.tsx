import { useValues } from 'kea'
import { useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { SparklineOptions } from '../components/SparklineChart/SparklineChart'

export function useSparklineOptions(overrides: Partial<SparklineOptions> = {}, deps: any[] = []): SparklineOptions {
    const colorVars = useDefaultSparklineColorVars()
    return useMemo(() => {
        return {
            backgroundColor: `var(--${colorVars[0]})`,
            hoverBackgroundColor: `var(--${colorVars[1]})`,
            axisColor: `var(--${colorVars[0]})`,
            borderRadius: 5,
            eventLabelHeight: 20,
            eventLabelPaddingX: 5,
            eventLabelPaddingY: 3,
            eventMinSpace: 2,
            minBarHeight: 10,
            ...overrides,
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [colorVars, ...deps])
}

const DARK_MODE_COLORS = ['color-zinc-400', 'color-zinc-200']
const LIGHT_MODE_COLORS = ['color-zinc-400', 'color-zinc-600']

export function useDefaultSparklineColorVars(): [string, string] {
    const { isDarkModeOn } = useValues(themeLogic)
    return useMemo(() => (isDarkModeOn ? DARK_MODE_COLORS : LIGHT_MODE_COLORS), [isDarkModeOn]) as [string, string]
}
