// Before-vs-after slope chart: one line per owned test, from its prior-window signal count to
// its current-window count. The comparison grammar for "many entities, exactly two periods":
// worsening tests slope up in red, improving ones slope down in green.

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface SlopeItem {
    label: string
    /** Hover detail; falls back to label. */
    tooltip?: string
    prior: number
    current: number
}

const WIDTH = 340
const ROW_HEIGHT = 26
const MIN_HEIGHT = 140
const PAD_X = 8
const PAD_Y = 14

function slopeColor(item: SlopeItem): string {
    if (item.current > item.prior) {
        return 'var(--danger)'
    }
    if (item.current < item.prior) {
        return 'var(--success)'
    }
    return 'var(--muted)'
}

function shortLabel(label: string): string {
    const test = label.split('::').pop() ?? label
    return test.length > 44 ? `${test.slice(0, 42)}…` : test
}

export function TeamTestSlopeChart({
    items,
    priorLabel,
    currentLabel,
}: {
    items: SlopeItem[]
    priorLabel: string
    currentLabel: string
}): JSX.Element {
    const shown = items.slice(0, 12)
    const max = Math.max(1, ...shown.flatMap((item) => [item.prior, item.current]))
    const height = Math.max(MIN_HEIGHT, Math.min(shown.length * ROW_HEIGHT, 320))
    const yFor = (value: number): number => PAD_Y + (1 - value / max) * (height - 2 * PAD_Y)

    return (
        <div className="flex items-stretch gap-4">
            <div className="flex flex-col">
                <svg
                    width={WIDTH}
                    height={height + 22}
                    viewBox={`0 0 ${WIDTH} ${height + 22}`}
                    role="img"
                    aria-label={`Per-test flaky signal, ${priorLabel} vs ${currentLabel}`}
                >
                    <line x1={PAD_X} y1={PAD_Y} x2={PAD_X} y2={height - PAD_Y} stroke="var(--border-primary)" />
                    <line
                        x1={WIDTH - PAD_X}
                        y1={PAD_Y}
                        x2={WIDTH - PAD_X}
                        y2={height - PAD_Y}
                        stroke="var(--border-primary)"
                    />
                    {shown.map((item) => (
                        <g key={item.label}>
                            <title>{`${item.tooltip ?? item.label}: ${item.prior} → ${item.current}`}</title>
                            <line
                                x1={PAD_X}
                                y1={yFor(item.prior)}
                                x2={WIDTH - PAD_X}
                                y2={yFor(item.current)}
                                stroke={slopeColor(item)}
                                strokeWidth={2}
                                strokeOpacity={0.85}
                            />
                            <circle cx={PAD_X} cy={yFor(item.prior)} r={4} fill={slopeColor(item)} />
                            <circle cx={WIDTH - PAD_X} cy={yFor(item.current)} r={4} fill={slopeColor(item)} />
                        </g>
                    ))}
                    <text x={PAD_X} y={height + 14} className="fill-current text-[10px]" textAnchor="start">
                        {priorLabel}
                    </text>
                    <text x={WIDTH - PAD_X} y={height + 14} className="fill-current text-[10px]" textAnchor="end">
                        {currentLabel}
                    </text>
                </svg>
            </div>
            <ul className="m-0 flex min-w-0 flex-1 list-none flex-col justify-center gap-1 p-0">
                {shown.map((item) => (
                    <li key={item.label} className="flex min-w-0 items-center gap-2 text-xs">
                        <span
                            className="inline-block size-2 shrink-0 rounded-full"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: slopeColor(item) }}
                        />
                        <Tooltip title={item.tooltip ?? item.label}>
                            <span className="min-w-0 truncate font-mono">{shortLabel(item.label)}</span>
                        </Tooltip>
                        <span
                            className={cn(
                                'ml-auto shrink-0 tabular-nums',
                                item.current > item.prior
                                    ? 'text-danger'
                                    : item.current < item.prior
                                      ? 'text-success'
                                      : 'text-tertiary'
                            )}
                        >
                            {item.prior} → {item.current}
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    )
}
