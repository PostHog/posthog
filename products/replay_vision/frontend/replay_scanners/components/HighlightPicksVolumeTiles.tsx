import { LemonSkeleton } from '@posthog/lemon-ui'

import type { WeeklyVolume } from '../highlightPicksStarter'

function hoursLabel(hours: number): string {
    return hours < 1 ? `${Math.max(1, Math.round(hours * 60))}m` : `${Math.round(hours)}h`
}

export function HighlightPicksVolumeTiles({
    volume,
    loading,
    dataAttr,
}: {
    volume: WeeklyVolume | null
    loading: boolean
    dataAttr: string
}): JSX.Element | null {
    if (!volume) {
        return loading ? <LemonSkeleton className="h-16 w-full rounded" /> : null
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
                    className="flex flex-col items-center gap-0.5 rounded border bg-bg-light px-1 py-2 text-center"
                >
                    <span className="text-xxs font-bold uppercase tracking-wide text-secondary">{label}</span>
                    <span className="text-xl font-bold leading-tight">{value}</span>
                    <span className="text-xxs text-secondary">{caption}</span>
                </div>
            ))}
        </div>
    )
}
