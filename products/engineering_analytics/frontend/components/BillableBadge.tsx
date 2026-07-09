import { formatCost, formatMinutes } from './runTables'

/**
 * Inline "billable minutes · est. cost", the single cost representation across every table and tile.
 * Muted "—" when there's no figure (jobs unsynced, free runner, or nothing billable).
 */
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
