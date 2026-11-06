import { useId, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

const WIDTH = 300
const HEIGHT = 64
const PAD = 6

export function GoalTrendChart({
    values,
    labels,
    reference,
    referenceLabel,
    tone = 'neutral',
    format,
}: {
    values: number[]
    labels: string[]
    reference: number | null
    referenceLabel: string
    tone?: 'neutral' | 'success' | 'warning'
    format: (value: number) => string
}): JSX.Element | null {
    const gradient = useId()
    const [hover, setHover] = useState<number | null>(null)
    if (values.length < 2) {
        return null
    }
    const all = reference === null ? values : [...values, reference]
    const low = Math.min(...all)
    const high = Math.max(...all)
    const span = high - low || Math.abs(high) || 1
    const min = low - span * 0.15
    const max = high + span * 0.15
    const x = (index: number): number => (index / (values.length - 1)) * WIDTH
    const y = (value: number): number => PAD + (1 - (value - min) / (max - min)) * (HEIGHT - PAD * 2)
    const line = values
        .map((value, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(value).toFixed(1)}`)
        .join(' ')
    const area = `${line} L${WIDTH},${HEIGHT} L0,${HEIGHT} Z`
    const color = tone === 'success' ? 'text-success' : tone === 'warning' ? 'text-warning' : 'text-secondary'
    const pct = (value: number): string => `${(y(value) / HEIGHT) * 100}%`
    const last = values[values.length - 1]
    const sparse = values.length === 2
    const labelBelow = reference !== null && y(Math.max(...values.slice(-Math.ceil(values.length / 3)))) < y(reference)
    return (
        <div className="flex flex-col gap-1">
            <div
                className={cn('relative h-16 w-full cursor-crosshair', color)}
                onMouseMove={(event) => {
                    const box = event.currentTarget.getBoundingClientRect()
                    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width))
                    setHover(Math.round(ratio * (values.length - 1)))
                }}
                onMouseLeave={() => setHover(null)}
            >
                <svg
                    viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                    preserveAspectRatio="none"
                    className="absolute inset-0 size-full overflow-visible"
                >
                    <defs>
                        <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
                            <stop offset="0%" stopColor="currentColor" stopOpacity="0.16" />
                            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
                        </linearGradient>
                    </defs>
                    {!sparse && <path d={area} fill={`url(#${gradient})`} />}
                    {reference !== null && (
                        <line
                            x1="0"
                            x2={WIDTH}
                            y1={y(reference)}
                            y2={y(reference)}
                            className="text-tertiary"
                            stroke="currentColor"
                            strokeDasharray="4 3"
                            vectorEffect="non-scaling-stroke"
                        />
                    )}
                    <path
                        d={line}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeDasharray={sparse ? '5 4' : undefined}
                        vectorEffect="non-scaling-stroke"
                    />
                </svg>
                <span
                    className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-current bg-surface-primary"
                    style={{ left: '0%', top: pct(values[0]), width: 8, height: 8 }}
                />
                <span
                    className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full bg-current"
                    style={{ left: '100%', top: pct(last), width: 8, height: 8 }}
                />
                {hover !== null && (
                    <>
                        <span
                            className="pointer-events-none absolute inset-y-0 w-px bg-[var(--color-border-primary)]"
                            style={{ left: `${(hover / (values.length - 1)) * 100}%` }}
                        />
                        <span
                            className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--color-bg-surface-primary)] bg-current"
                            style={{ left: `${(hover / (values.length - 1)) * 100}%`, top: pct(values[hover]) }}
                        />
                        <span
                            className={cn(
                                'pointer-events-none absolute top-0 z-10 flex flex-col gap-0.5 whitespace-nowrap rounded border border-primary bg-surface-primary px-2 py-1 text-xs shadow-sm',
                                hover / (values.length - 1) > 0.6 ? '-translate-x-full -ms-2' : 'ms-2'
                            )}
                            style={{ left: `${(hover / (values.length - 1)) * 100}%` }}
                        >
                            <span className="text-tertiary">{labels[hover]}</span>
                            <span className="font-semibold text-primary tabular-nums">{format(values[hover])}</span>
                            {reference !== null && (
                                <span className="text-tertiary tabular-nums">
                                    {referenceLabel} {format(reference)}
                                </span>
                            )}
                        </span>
                    </>
                )}
                {reference !== null && (
                    <span
                        className={cn(
                            'absolute right-3 text-[10px] leading-none text-tertiary tabular-nums',
                            labelBelow ? 'pt-1' : '-translate-y-full pb-1'
                        )}
                        style={{ top: pct(reference) }}
                    >
                        {referenceLabel} {format(reference)}
                    </span>
                )}
            </div>
            <div className="flex justify-between text-[10px] leading-none text-tertiary">
                <span>{labels[0]}</span>
                {sparse && <span>Only the start and end are known</span>}
                <span>{labels[labels.length - 1]}</span>
            </div>
        </div>
    )
}
