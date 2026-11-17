import type { ReactElement } from 'react'
import { View } from 'react-native'
import Svg, { Rect } from 'react-native-svg'

import { useColors } from '@/ui/theme'

import { sparkBars } from './barLayout'

const BAR_RADIUS = 1.5
const BASELINE = 1

interface SparkBarsProps {
    /** One count per bucket, oldest first. */
    values: readonly number[]
    height: number
    color: string
    /** Bars from `highlightFrom` on draw in this color. */
    highlightColor: string
    /** Null draws every bar in `color`. */
    highlightFrom: number | null
    testID?: string
}

/**
 * Small zero-based bars on a baseline, for counts per bucket. It takes no touches: the row around it is the tap target.
 * SVG keeps it off the Skia canvas budget, so a list can draw one in every row.
 */
export function SparkBars({
    values,
    height,
    color,
    highlightColor,
    highlightFrom,
    testID,
}: SparkBarsProps): ReactElement {
    const colors = useColors()
    return (
        <View
            style={{ height }}
            testID={testID}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
        >
            <Svg width="100%" height={height}>
                <Rect x={0} y={height - BASELINE} width="100%" height={BASELINE} fill={colors.rowDivider} />
                {sparkBars(values, height, highlightFrom).map((bar) => (
                    <Rect
                        key={bar.x}
                        x={`${bar.x}%`}
                        y={height - bar.height}
                        width={`${bar.width}%`}
                        height={bar.height}
                        rx={Math.min(BAR_RADIUS, bar.height / 2)}
                        fill={bar.highlighted ? highlightColor : color}
                    />
                ))}
            </Svg>
        </View>
    )
}
