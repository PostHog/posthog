import type { SurfaceSegment } from '../suggestionCopy'

export interface ReadsBySurfaceBarProps {
    segments: SurfaceSegment[]
}

function segmentColor(index: number): string {
    return `var(--data-color-${index + 1})`
}

export function ReadsBySurfaceBar({ segments }: ReadsBySurfaceBarProps): JSX.Element {
    const total = segments.reduce((sum, segment) => sum + segment.count, 0)
    const description = segments.map((segment) => `${segment.label} ${segment.count}`).join(', ')

    return (
        <div className="flex flex-col gap-1.5">
            <div
                role="img"
                aria-label={`Reads by surface: ${description}`}
                className="flex h-2 w-full overflow-hidden rounded-full bg-fill-secondary"
            >
                {segments.map((segment, index) => (
                    <div
                        key={segment.key}
                        style={{ width: `${(segment.count / total) * 100}%`, backgroundColor: segmentColor(index) }}
                    />
                ))}
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                {segments.map((segment, index) => (
                    <span key={segment.key} className="inline-flex items-center gap-1">
                        <span
                            aria-hidden
                            className="inline-block size-2 rounded-sm"
                            style={{ backgroundColor: segmentColor(index) }}
                        />
                        <span>{segment.label}</span>
                        <span translate="no" className="font-semibold tabular-nums">
                            {segment.count}
                        </span>
                    </span>
                ))}
            </div>
        </div>
    )
}
