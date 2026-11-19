import type { ReactElement } from 'react'
import { type DimensionValue, View } from 'react-native'
import Svg, { Path } from 'react-native-svg'

import { createStyles, useColors } from '@/ui/theme'

const VIEW_WIDTH = 100
const VIEW_HEIGHT = 32
// The line keeps 2 units of room at the top and bottom of the 32-unit box, so a 2pt stroke never clips.
const PLOT_TOP = 2
const PLOT_BOTTOM = 30
const AREA_OPACITY = 0.1
const DOT_RING = 2
// A 9pt dot inside a ring of the card color, so it stays visible where it sits on the line.
const DOT_SIZE = 9 + DOT_RING * 2

interface SparklineProps {
    /** One value per bucket. NaN = gap. */
    values: readonly number[]
    /** Buckets from this index on draw in `color` with an area under them; earlier ones draw gray. Defaults to 0. */
    highlightFrom?: number
    color?: string
    /** Defaults to 132 × 40, the Number pin's size. A number or a percentage. */
    width?: DimensionValue
    height?: number
    /** A dot on the last value. Defaults to true. */
    showDot?: boolean
    testID?: string
}

interface Scaled {
    x: number
    y: number
}

function scale(values: readonly number[]): (Scaled | null)[] {
    const finite = values.filter(Number.isFinite)
    if (finite.length === 0) {
        return values.map(() => null)
    }
    const min = Math.min(...finite)
    const max = Math.max(...finite)
    const span = max - min
    // The floor sits below the lowest value, so a flat-ish series reads as a line in the middle, not on the floor.
    const lo = Math.max(0, min - span * 0.6)
    const hi = max + span * 0.1 || 1
    const last = Math.max(1, values.length - 1)
    return values.map((value, index) =>
        Number.isFinite(value)
            ? {
                  x: (index / last) * VIEW_WIDTH,
                  y: PLOT_BOTTOM - ((value - lo) / (hi - lo || 1)) * (PLOT_BOTTOM - PLOT_TOP),
              }
            : null
    )
}

function linePath(points: (Scaled | null)[]): string {
    let path = ''
    let pen = false
    for (const point of points) {
        if (!point) {
            pen = false
            continue
        }
        path += `${pen ? 'L' : 'M'}${point.x.toFixed(2)} ${point.y.toFixed(2)}`
        pen = true
    }
    return path
}

function areaPath(points: (Scaled | null)[]): string {
    const drawn = points.filter((point): point is Scaled => point !== null)
    const first = drawn[0]
    const last = drawn[drawn.length - 1]
    if (!first || !last || drawn.length < 2) {
        return ''
    }
    return `${linePath(drawn)}L${last.x.toFixed(2)} ${VIEW_HEIGHT}L${first.x.toFixed(2)} ${VIEW_HEIGHT}Z`
}

/**
 * A small trend line in SVG, for Number pins and for Chart pins that wait for a canvas. It takes no touches: the whole
 * row around it is the tap target. SVG keeps it off the Skia canvas budget and off CanvasKit on web.
 */
export function Sparkline({
    values,
    highlightFrom = 0,
    color: colorProp,
    width = 132,
    height = 40,
    showDot = true,
    testID,
}: SparklineProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const color = colorProp ?? colors.blue
    const points = scale(values)
    const from = Math.max(0, Math.min(highlightFrom, points.length - 1))
    // The gray part ends on the first highlighted bucket, so the two parts join without a gap.
    const before = from > 0 ? linePath(points.slice(0, from + 1)) : ''
    const current = points.slice(from)
    const lastPoint = [...points].reverse().find((point) => point !== null)
    return (
        <View
            style={{ width, height }}
            testID={testID}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
        >
            <Svg width="100%" height="100%" viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`} preserveAspectRatio="none">
                <Path d={areaPath(current)} fill={color} fillOpacity={AREA_OPACITY} />
                {before ? (
                    <Path
                        d={before}
                        fill="none"
                        stroke={colors.disabled}
                        strokeWidth={2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        vectorEffect="non-scaling-stroke"
                    />
                ) : null}
                <Path
                    d={linePath(current)}
                    fill="none"
                    stroke={color}
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    vectorEffect="non-scaling-stroke"
                />
            </Svg>
            {showDot && lastPoint ? (
                <View
                    style={[
                        styles.dot,
                        {
                            backgroundColor: color,
                            left: `${(lastPoint.x / VIEW_WIDTH) * 100}%`,
                            top: `${(lastPoint.y / VIEW_HEIGHT) * 100}%`,
                        },
                    ]}
                />
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    dot: {
        position: 'absolute',
        width: DOT_SIZE,
        height: DOT_SIZE,
        marginLeft: -DOT_SIZE / 2,
        marginTop: -DOT_SIZE / 2,
        borderRadius: DOT_SIZE / 2,
        borderWidth: DOT_RING,
        borderColor: colors.surface,
    },
}))
