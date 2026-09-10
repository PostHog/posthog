import {
    NumberSketch,
    PieSketch,
    TableSketch,
    TrendsSketch,
    WorldMapSketch,
} from 'scenes/saved-insights/InsightTypeSketch'

import { ChartDisplayType } from '~/types'

const AXIS = 'var(--color-border-primary)'
const INK = 'var(--data-color-1)'
const INK_ALT = 'var(--data-color-14)'

export function ChartDisplaySketch({ display }: { display: ChartDisplayType }): JSX.Element {
    switch (display) {
        case ChartDisplayType.BoldNumber:
            return <NumberSketch />
        case ChartDisplayType.Metric:
            return <MetricSketch />
        case ChartDisplayType.ActionsPie:
            return <PieSketch />
        case ChartDisplayType.ActionsDonut:
            return <DonutSketch />
        case ChartDisplayType.ActionsTable:
            return <TableSketch />
        case ChartDisplayType.WorldMap:
            return <WorldMapSketch />
        case ChartDisplayType.ActionsAreaGraph:
            return <AreaSketch />
        case ChartDisplayType.ActionsUnstackedBar:
            return <BarSketch />
        case ChartDisplayType.ActionsBar:
        case ChartDisplayType.ActionsStackedBar:
            return <StackedBarSketch />
        case ChartDisplayType.ActionsBarValue:
            return <HorizontalBarSketch />
        case ChartDisplayType.BoxPlot:
            return <BoxPlotSketch />
        case ChartDisplayType.CalendarHeatmap:
            return <CalendarHeatmapSketch />
        case ChartDisplayType.SlopeGraph:
            return <SlopeGraphSketch />
        case ChartDisplayType.ActionsLineGraphCumulative:
            return (
                <SketchSvg>
                    <path d="M12 10 V74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" />
                    <path d="M14 70 L40 65 L65 52 L90 46 L115 28 L147 12" stroke={INK} strokeWidth="2.5" />
                </SketchSvg>
            )
        default:
            return <TrendsSketch />
    }
}

function SketchSvg({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <svg viewBox="0 0 160 88" className="w-full h-auto" fill="none" aria-hidden="true">
            {children}
        </svg>
    )
}

function BarSketch(): JSX.Element {
    const heights = [35, 52, 25, 60, 43, 31]
    return (
        <SketchSvg>
            <path d="M12 74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" />
            {heights.map((height, index) => (
                <rect
                    key={index}
                    x={16 + index * 22}
                    y={74 - height}
                    width="14"
                    height={height}
                    rx="2"
                    fill={INK}
                    opacity={0.45 + index * 0.09}
                />
            ))}
        </SketchSvg>
    )
}

function StackedBarSketch(): JSX.Element {
    const bars = [
        [27, 17],
        [34, 24],
        [20, 16],
        [38, 28],
        [26, 19],
    ]
    return (
        <SketchSvg>
            <path d="M12 74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" />
            {bars.map(([lower, upper], index) => (
                <g key={index}>
                    <rect x={18 + index * 27} y={74 - lower} width="18" height={lower} rx="2" fill={INK} />
                    <rect
                        x={18 + index * 27}
                        y={74 - lower - upper}
                        width="18"
                        height={upper}
                        rx="2"
                        fill={INK_ALT}
                        opacity="0.7"
                    />
                </g>
            ))}
        </SketchSvg>
    )
}

function HorizontalBarSketch(): JSX.Element {
    return (
        <SketchSvg>
            {[86, 63, 43, 29].map((width, index) => (
                <g key={width}>
                    <rect x="14" y={14 + index * 16} width="18" height="6" rx="3" fill={AXIS} />
                    <rect
                        x="38"
                        y={12 + index * 16}
                        width={width}
                        height="10"
                        rx="2"
                        fill={INK}
                        opacity={1 - index * 0.16}
                    />
                </g>
            ))}
        </SketchSvg>
    )
}

function AreaSketch(): JSX.Element {
    return (
        <SketchSvg>
            <path d="M12 10 V74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" />
            <path
                d="M14 60 C 35 58, 45 42, 65 45 C 85 48, 92 29, 108 33 C 123 37, 133 17, 147 13 V74 H14 Z"
                fill={INK}
                opacity="0.22"
            />
            <path
                d="M14 60 C 35 58, 45 42, 65 45 C 85 48, 92 29, 108 33 C 123 37, 133 17, 147 13"
                stroke={INK}
                strokeWidth="2.5"
                strokeLinecap="round"
            />
        </SketchSvg>
    )
}

function BoxPlotSketch(): JSX.Element {
    const plots = [
        [30, 43, 20],
        [52, 30, 16],
        [75, 42, 21],
        [99, 22, 19],
        [124, 36, 17],
    ]
    return (
        <SketchSvg>
            <path d="M12 74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" />
            {plots.map(([x, top, height]) => (
                <g key={x} stroke={INK} strokeWidth="2">
                    <path
                        d={`M${x} ${top - 8} V${top + height + 8} M${x - 5} ${top - 8} H${x + 5} M${x - 5} ${top + height + 8} H${x + 5}`}
                    />
                    <rect x={x - 8} y={top} width="16" height={height} fill={INK} fillOpacity="0.2" />
                    <path d={`M${x - 8} ${top + height / 2} H${x + 8}`} />
                </g>
            ))}
        </SketchSvg>
    )
}

function CalendarHeatmapSketch(): JSX.Element {
    return (
        <SketchSvg>
            {Array.from({ length: 7 }, (_, row) =>
                Array.from({ length: 12 }, (_, column) => {
                    const opacity = ((row * 3 + column * 5) % 7) / 8 + 0.15
                    return (
                        <rect
                            key={`${row}-${column}`}
                            x={14 + column * 11}
                            y={11 + row * 10}
                            width="8"
                            height="7"
                            rx="1.5"
                            fill={INK}
                            opacity={opacity}
                        />
                    )
                })
            )}
        </SketchSvg>
    )
}

function SlopeGraphSketch(): JSX.Element {
    return (
        <SketchSvg>
            <path d="M28 12 V74 M132 12 V74" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" />
            {[
                [21, 59],
                [37, 26],
                [53, 46],
                [66, 31],
            ].map(([start, end], index) => (
                <path
                    key={index}
                    d={`M28 ${start} L132 ${end}`}
                    stroke={index % 2 ? INK_ALT : INK}
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    opacity={1 - index * 0.14}
                />
            ))}
        </SketchSvg>
    )
}

function DonutSketch(): JSX.Element {
    return (
        <SketchSvg>
            <circle cx="80" cy="44" r="24" stroke={INK} strokeWidth="16" strokeDasharray="92 59" />
            <circle
                cx="80"
                cy="44"
                r="24"
                stroke={INK_ALT}
                strokeWidth="16"
                strokeDasharray="33 118"
                strokeDashoffset="-98"
            />
        </SketchSvg>
    )
}

function MetricSketch(): JSX.Element {
    return (
        <SketchSvg>
            <rect x="15" y="12" width="130" height="64" rx="4" stroke={AXIS} strokeWidth="1.5" />
            <text x="25" y="42" fill="var(--color-text-primary)" fontSize="23" fontWeight="700">
                1,024
            </text>
            <path
                d="M24 64 C 39 61, 49 65, 61 55 C 72 46, 82 60, 93 48 C 105 35, 119 45, 136 25"
                stroke={INK}
                strokeWidth="2.5"
                strokeLinecap="round"
            />
        </SketchSvg>
    )
}
