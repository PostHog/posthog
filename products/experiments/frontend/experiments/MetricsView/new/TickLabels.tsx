import { COLORS } from '../shared/colors'
import { formatTickValue } from '../shared/utils'

interface TickLabelsProps {
    tickValues: number[]
    scale: (value: number) => number
    y: number
    viewBoxWidth?: number
    fontSize?: number
    fontWeight?: string | number
    textColor?: string
    textAnchor?: 'start' | 'middle' | 'end'
    dominantBaseline?: 'auto' | 'middle' | 'hanging'
    edgeThreshold?: number
    svgWidth?: number // Actual rendered width of the SVG
}

/**
 * Renders tick labels for experiment charts.
 * Uses formatTickValue to display percentages with appropriate precision.
 */
export function TickLabels({
    tickValues,
    scale,
    y,
    viewBoxWidth = 800,
    fontSize = 9,
    fontWeight = '600',
    textColor = COLORS.TICK_TEXT_COLOR,
    textAnchor = 'middle',
    dominantBaseline = 'middle',
    edgeThreshold = 0.06,
    svgWidth,
}: TickLabelsProps): JSX.Element {
    // Calculate scale factor to compensate for SVG scaling
    const scaleFactor = svgWidth ? viewBoxWidth / svgWidth : 1
    return (
        <>
            {tickValues.map((value) => {
                const x = scale(value)
                const position = x / viewBoxWidth

                // Hide labels that are too close to the edges to prevent clipping
                if (position < edgeThreshold || position > 1 - edgeThreshold) {
                    return null
                }

                return (
                    <text
                        key={`text-${value}`}
                        x={x}
                        y={y}
                        textAnchor={textAnchor}
                        dominantBaseline={dominantBaseline}
                        fill={textColor}
                        fontWeight={fontWeight}
                        style={{
                            fontSize: `${fontSize * scaleFactor}px`,
                        }}
                    >
                        {formatTickValue(value)}
                    </text>
                )
            })}
        </>
    )
}
