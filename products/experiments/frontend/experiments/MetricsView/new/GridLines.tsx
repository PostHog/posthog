import { COLORS } from '../shared/colors'

interface GridLinesProps {
    tickValues: number[]
    scale: (value: number) => number
    height: number
    viewBoxWidth?: number
    zeroLineColor?: string
    gridLineColor?: string
    zeroLineWidth?: number
    gridLineWidth?: number
    opacity?: number
    edgeThreshold?: number
    edgeMargin?: number
}

/**
 * Renders vertical grid lines for experiment charts.
 * Zero line is rendered with different styling to emphasize the baseline.
 */
export function GridLines({
    tickValues,
    scale,
    height,
    viewBoxWidth = 800,
    zeroLineColor = COLORS.ZERO_LINE,
    gridLineColor = COLORS.BOUNDARY_LINES,
    zeroLineWidth = 1.25,
    gridLineWidth = 0.75,
    opacity = 1,
    edgeThreshold = 0.06,
    edgeMargin = 20,
}: GridLinesProps): JSX.Element {
    return (
        <>
            {tickValues.map((value) => {
                const x = scale(value)
                // Calculate position considering edge margins
                const usableWidth = viewBoxWidth - 2 * edgeMargin
                const position = (x - edgeMargin) / usableWidth
                const isZeroLine = value === 0

                // Hide grid lines that are too close to the edges, but always show zero line
                if (!isZeroLine && (position < edgeThreshold || position > 1 - edgeThreshold)) {
                    return null
                }

                return (
                    <line
                        key={value}
                        x1={x}
                        y1={0}
                        x2={x}
                        y2={height}
                        stroke={isZeroLine ? zeroLineColor : gridLineColor}
                        strokeWidth={isZeroLine ? zeroLineWidth : gridLineWidth}
                        opacity={opacity}
                    />
                )
            })}
        </>
    )
}
