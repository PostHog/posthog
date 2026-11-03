import { Skeleton } from '@posthog/quill'

import type { WeeklyVolume } from '../highlightPicksStarter'

function hoursLabel(hours: number): string {
    return hours < 1 ? `${Math.max(1, Math.round(hours * 60))}m` : `${Math.round(hours)}h`
}

export function QuillHighlightPicksVolumeTiles({
    volume,
    loading,
    dataAttr,
}: {
    volume: WeeklyVolume | null
    loading: boolean
    dataAttr: string
}): JSX.Element | null {
    if (!volume) {
        return loading ? <Skeleton className="h-16 w-full rounded" /> : null
    }
    const tiles: [string, string, string][] = [
        ['Recorded', String(volume.recorded), 'a week, estimated'],
        ['To watch', volume.hours === null ? '-' : hoursLabel(volume.hours), 'at normal speed'],
    ]
    return (
        <div className="grid grid-cols-2 gap-1.5" data-attr={dataAttr}>
            {tiles.map(([label, value, caption]) => (
                <div
                    key={label}
                    className="flex flex-col items-center gap-0.5 rounded border border-border bg-background px-1 py-2 text-center"
                >
                    <span className="text-xxs font-bold uppercase tracking-wide text-muted-foreground">{label}</span>
                    <span className="text-xl font-bold leading-tight text-foreground">{value}</span>
                    <span className="text-xxs text-muted-foreground">{caption}</span>
                </div>
            ))}
        </div>
    )
}
