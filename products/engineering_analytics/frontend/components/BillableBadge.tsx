import { formatCost, formatMinutes } from './runTables'

/**
 * Unified inline "billable minutes · est. cost" — the single cost representation across every table and
 * tile (PR list, workflow table, author page, per-runner breakdown). Muted "—" when there's no figure
 * (jobs source unsynced, or nothing billable). GitHub-hosted/free runners carry no billable cost, so
 * the caller simply passes nulls for those.
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
