import { LEGACY_COLORS } from './legacyColors'
import { legacyFormatTickValue } from './legacyUtils'

interface LegacyTickPanelProps {
    tickValues: number[]
    valueToX: (value: number) => number
    viewBoxWidth: number
    tickPanelHeight: number
    svgRef?: React.RefObject<SVGSVGElement> // Optional ref for resize observation
}

/**
 * @deprecated
 * Legacy tick panel component for MetricsView.
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyTickPanel({
    tickValues,
    valueToX,
    viewBoxWidth,
    tickPanelHeight,
    svgRef,
}: LegacyTickPanelProps): JSX.Element {
    const TICK_FONT_SIZE = 9
    const colors = LEGACY_COLORS

    return (
        <svg
            ref={svgRef}
            viewBox={`0 0 ${viewBoxWidth} ${tickPanelHeight}`}
            preserveAspectRatio="xMidYMid meet"
            className="ml-12 max-w-[1000px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ minHeight: `${tickPanelHeight}px` }} // Dynamic height based on panel configuration
        >
            {tickValues.map((value) => {
                const x = valueToX(value)
                return (
                    <g key={value}>
                        <text
                            x={x}
                            y={tickPanelHeight / 2}
                            textAnchor="middle"
                            dominantBaseline="middle"
                            fontSize={TICK_FONT_SIZE}
                            fill={colors.TICK_TEXT_COLOR}
                            fontWeight="600"
                        >
                            {legacyFormatTickValue(value)}
                        </text>
                    </g>
                )
            })}
        </svg>
    )
}
