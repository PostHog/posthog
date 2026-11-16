import { formatCost, formatMinutes } from './runTables'

export function BillableBadge({
    minutes,
    costUsd,
    available = true,
}: {
    minutes?: number | null
    costUsd?: number | null
    available?: boolean
}): JSX.Element {
    if (!available || (minutes == null && costUsd == null)) {
        return <span className="text-xs text-secondary">—</span>
    }
    const parts = [formatMinutes(minutes ?? null), formatCost(costUsd ?? null)].filter((part) => part !== '—')
    return <span className="text-xs whitespace-nowrap tabular-nums">{parts.length ? parts.join(' · ') : '—'}</span>
}
