import { InsightType } from '~/types'

import { WORLD_MAP_BASE_D, WORLD_MAP_HIGHLIGHTS } from './worldMapSketchData'

// Hand-drawn-style previews for the new insight picker. Colors come from theme
// CSS variables so the sketches adapt to light/dark mode automatically.
const AXIS = 'var(--color-border-primary)'
const TEXT = 'var(--color-text-primary)'
const TEXT_MUTED = 'var(--color-text-secondary)'
const INK = 'var(--data-color-1)'
const INK_ALT = 'var(--data-color-14)'
const INK_UP = 'var(--data-color-7)'
const INK_DOWN = 'var(--data-color-5)'
const INK_AI = 'var(--color-ai)'

function SketchSvg({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <svg viewBox="0 0 160 88" className="w-full h-auto" fill="none" aria-hidden="true">
            {children}
        </svg>
    )
}

function Star({ cx, cy, r, fill }: { cx: number; cy: number; r: number; fill: string }): JSX.Element {
    const inner = r * 0.32
    return (
        <path
            d={`M${cx} ${cy - r} L${cx + inner} ${cy - inner} L${cx + r} ${cy} L${cx + inner} ${cy + inner} L${cx} ${cy + r} L${cx - inner} ${cy + inner} L${cx - r} ${cy} L${cx - inner} ${cy - inner} Z`}
            fill={fill}
        />
    )
}

export function TrendsSketch(): JSX.Element {
    return (
        <SketchSvg>
            <path d="M12 10 V74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" strokeLinecap="round" />
            <path
                d="M14 68 C 30 66, 40 62, 54 61 C 68 60, 78 54, 92 52 C 106 50, 118 46, 130 42 C 138 39.5, 143 38, 147 36"
                stroke={INK_ALT}
                strokeWidth="2.5"
                strokeLinecap="round"
                opacity="0.6"
            />
            <path
                d="M14 60 C 24 59, 32 50, 42 51 C 52 52, 58 40, 70 38 C 82 36, 88 44, 100 36 C 112 28, 120 30, 132 20 C 138 15, 143 14, 147 11"
                stroke={INK}
                strokeWidth="2.5"
                strokeLinecap="round"
            />
            {[
                [42, 51],
                [70, 38],
                [100, 36],
                [132, 20],
            ].map(([cx, cy]) => (
                <circle key={cx} cx={cx} cy={cy} r="3" fill={INK} />
            ))}
        </SketchSvg>
    )
}

export function FunnelSketch(): JSX.Element {
    const bars: [number, number][] = [
        [14, 56],
        [50, 36],
        [86, 22],
        [122, 12],
    ]
    return (
        <SketchSvg>
            <path d="M12 74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" strokeLinecap="round" />
            {bars.map(([x, height], index) => (
                <rect
                    key={x}
                    x={x}
                    y={74 - height}
                    width="28"
                    height={height}
                    rx="3"
                    fill={INK}
                    opacity={1 - index * 0.24}
                />
            ))}
            {bars.slice(0, -1).map(([x, height], index) => {
                const [nextX, nextHeight] = bars[index + 1]
                return (
                    <path
                        key={x}
                        d={`M${x + 28} ${74 - height} L${nextX} ${74 - nextHeight} V74 H${x + 28} Z`}
                        fill={INK}
                        opacity="0.1"
                    />
                )
            })}
        </SketchSvg>
    )
}

export function RetentionSketch(): JSX.Element {
    return (
        <SketchSvg>
            {[7, 6, 5, 4].map((cells, row) => (
                <g key={row}>
                    {Array.from({ length: cells }, (_, col) => (
                        <rect
                            key={col}
                            x={14 + col * 19}
                            y={14 + row * 15}
                            width="16"
                            height="11"
                            rx="2"
                            fill={INK}
                            opacity={Math.max(0.2, 0.95 - col * 0.13)}
                        />
                    ))}
                </g>
            ))}
        </SketchSvg>
    )
}

export function PathsSketch(): JSX.Element {
    return (
        <SketchSvg>
            <path d="M21 34 C 60 34, 85 20, 138 20" stroke={INK} strokeWidth="11" strokeLinecap="round" opacity="0.3" />
            <path d="M21 45 C 60 45, 85 47, 138 48" stroke={INK} strokeWidth="8" strokeLinecap="round" opacity="0.22" />
            <path
                d="M21 55 C 55 56, 85 70, 138 70"
                stroke={INK}
                strokeWidth="5.5"
                strokeLinecap="round"
                opacity="0.15"
            />
            <rect x="12" y="28" width="9" height="32" rx="2.5" fill={INK} opacity="0.9" />
            <rect x="138" y="13" width="9" height="15" rx="2.5" fill={INK} opacity="0.75" />
            <rect x="138" y="41" width="9" height="13" rx="2.5" fill={INK} opacity="0.55" />
            <rect x="138" y="64" width="9" height="11" rx="2.5" fill={INK} opacity="0.4" />
        </SketchSvg>
    )
}

export function StickinessSketch(): JSX.Element {
    const heights = [54, 38, 27, 19, 13, 9, 6]
    return (
        <SketchSvg>
            <path d="M12 74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" strokeLinecap="round" />
            {heights.map((height, index) => (
                <rect
                    key={index}
                    x={14 + index * 19}
                    y={74 - height}
                    width="14"
                    height={height}
                    rx="2"
                    fill={INK}
                    opacity={Math.max(0.35, 1 - index * 0.11)}
                />
            ))}
        </SketchSvg>
    )
}

export function LifecycleSketch(): JSX.Element {
    const up = [16, 22, 13, 26, 18, 24]
    const down = [9, 13, 18, 7, 15, 11]
    return (
        <SketchSvg>
            {up.map((height, index) => (
                <rect
                    key={index}
                    x={16 + index * 22}
                    y={45 - 2 - height}
                    width="15"
                    height={height}
                    rx="2"
                    fill={INK_UP}
                    opacity="0.85"
                />
            ))}
            {down.map((height, index) => (
                <rect
                    key={index}
                    x={16 + index * 22}
                    y={47}
                    width="15"
                    height={height}
                    rx="2"
                    fill={INK_DOWN}
                    opacity="0.7"
                />
            ))}
            <path d="M12 45 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" strokeLinecap="round" />
        </SketchSvg>
    )
}

export function SqlSketch(): JSX.Element {
    return (
        <SketchSvg>
            <rect x="14" y="14" width="26" height="6" rx="3" fill={INK} />
            <rect x="44" y="14" width="40" height="6" rx="3" fill={AXIS} />
            <rect x="14" y="26" width="18" height="6" rx="3" fill={INK_ALT} />
            <rect x="36" y="26" width="52" height="6" rx="3" fill={AXIS} />
            <rect x="14" y="38" width="30" height="6" rx="3" fill={INK} />
            <rect x="48" y="38" width="24" height="6" rx="3" fill={AXIS} />
            <rect x="76" y="38" width="20" height="6" rx="3" fill="var(--data-color-4)" />
            <rect x="14" y="54" width="118" height="24" rx="3" stroke={AXIS} strokeWidth="1.5" />
            <path d="M14 66 H132 M55 54 V78 M96 54 V78" stroke={AXIS} strokeWidth="1.5" />
        </SketchSvg>
    )
}

export function AiSketch(): JSX.Element {
    return (
        <SketchSvg>
            <rect x="14" y="12" width="132" height="16" rx="8" stroke={AXIS} strokeWidth="1.5" />
            <rect x="22" y="18" width="46" height="4" rx="2" fill={AXIS} />
            <Star cx={134} cy={20} r={6} fill={INK_AI} />
            <path
                d="M14 72 C 28 71, 38 62, 52 61 C 66 60, 74 50, 90 46 C 106 42, 116 34, 130 28 C 137 25, 142 24, 146 22"
                stroke={INK_AI}
                strokeWidth="2.5"
                strokeLinecap="round"
            />
            {[
                [52, 61],
                [90, 46],
                [130, 28],
            ].map(([cx, cy]) => (
                <circle key={cx} cx={cx} cy={cy} r="2.5" fill={INK_AI} />
            ))}
            <Star cx={112} cy={56} r={4} fill={INK_AI} />
        </SketchSvg>
    )
}

export function WorldMapSketch(): JSX.Element {
    return (
        <SketchSvg>
            {/* Mirrors the insight: countries without data in border color, countries with data shaded by value */}
            <path d={WORLD_MAP_BASE_D} fill={AXIS} fillRule="evenodd" />
            {/* Hairline stroke keeps thin necks (e.g. New England) visible at sketch scale */}
            {WORLD_MAP_HIGHLIGHTS.map(({ opacity, d }, index) => (
                <path
                    key={index}
                    d={d}
                    fill={INK}
                    fillRule="evenodd"
                    stroke={INK}
                    strokeWidth="0.6"
                    strokeLinejoin="round"
                    opacity={opacity}
                />
            ))}
        </SketchSvg>
    )
}

export function TableSketch(): JSX.Element {
    const values = [64, 44, 30, 18]
    return (
        <SketchSvg>
            <rect x="14" y="12" width="132" height="64" rx="3" stroke={AXIS} strokeWidth="1.5" />
            <path d="M14 26 H146 M14 40 H146 M14 54 H146 M14 68 H146" stroke={AXIS} strokeWidth="1" opacity="0.6" />
            <path d="M62 12 V76" stroke={AXIS} strokeWidth="1" opacity="0.6" />
            <rect x="20" y="16" width="28" height="5" rx="2.5" fill={INK_ALT} />
            <rect x="68" y="16" width="20" height="5" rx="2.5" fill={INK_ALT} />
            {values.map((value, index) => (
                <g key={index}>
                    <rect x="20" y={30 + index * 14} width={34 - index * 5} height="5" rx="2.5" fill={AXIS} />
                    <rect
                        x="68"
                        y={30 + index * 14}
                        width={value}
                        height="5"
                        rx="2.5"
                        fill={INK}
                        opacity={1 - index * 0.18}
                    />
                </g>
            ))}
        </SketchSvg>
    )
}

export function NumberSketch(): JSX.Element {
    return (
        <SketchSvg>
            {/* Mirrors BoldNumber: one huge centered value, comparison row below */}
            <text x="80" y="50" textAnchor="middle" fill={TEXT} fontSize="38" fontWeight="700" letterSpacing="-0.95">
                1,024
            </text>
            {/* "Up 12% from previous period" — trending icon + text bars, link in accent */}
            <path
                d="M41 68 L46 63 L49.5 66 L55 60.5 M51.5 60.5 H55 V64"
                stroke={TEXT_MUTED}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <rect x="60" y="62" width="34" height="5" rx="2.5" fill={TEXT_MUTED} opacity="0.45" />
            <rect x="97" y="62" width="22" height="5" rx="2.5" fill={INK} opacity="0.8" />
        </SketchSvg>
    )
}

export function PieSketch(): JSX.Element {
    return (
        <SketchSvg>
            <path d="M80 44 L80 16 A28 28 0 0 1 80 72 Z" fill={INK} opacity="0.9" />
            <path d="M80 44 L80 72 A28 28 0 0 1 53.4 35.3 Z" fill={INK} opacity="0.5" />
            <path d="M80 44 L53.4 35.3 A28 28 0 0 1 80 16 Z" fill={INK} opacity="0.25" />
        </SketchSvg>
    )
}

/** Fallback for insight types without a dedicated sketch. */
export function GenericInsightSketch(): JSX.Element {
    const heights = [22, 38, 30, 48, 40, 56]
    return (
        <SketchSvg>
            <path d="M12 74 H148" stroke={AXIS} strokeWidth="1.5" strokeDasharray="3 4" strokeLinecap="round" />
            {heights.map((height, index) => (
                <rect
                    key={index}
                    x={16 + index * 22}
                    y={74 - height}
                    width="15"
                    height={height}
                    rx="2"
                    fill={INK}
                    opacity="0.7"
                />
            ))}
        </SketchSvg>
    )
}

export const INSIGHT_TYPE_SKETCHES: Partial<Record<InsightType, () => JSX.Element>> = {
    [InsightType.TRENDS]: TrendsSketch,
    [InsightType.FUNNELS]: FunnelSketch,
    [InsightType.RETENTION]: RetentionSketch,
    [InsightType.PATHS]: PathsSketch,
    [InsightType.STICKINESS]: StickinessSketch,
    [InsightType.LIFECYCLE]: LifecycleSketch,
    [InsightType.SQL]: SqlSketch,
}
