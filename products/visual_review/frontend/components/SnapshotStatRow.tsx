export type StatPreset = 'all' | 'tolerated_drift' | 'currently_quarantined'

const COLOR_BY_PRESET: Record<StatPreset, string> = {
    all: 'var(--text-tertiary)',
    tolerated_drift: 'var(--primary-3000)',
    currently_quarantined: 'var(--warning-dark)',
}

const STATS: Array<{ value: StatPreset; label: string; description: string }> = [
    { value: 'all', label: 'All snapshots', description: 'Every baseline image' },
    {
        value: 'tolerated_drift',
        label: 'Tolerated drift',
        description: 'At least one tolerate in the last 30 days',
    },
    {
        value: 'currently_quarantined',
        label: 'Currently quarantined',
        description: 'Marked unreliable — skipped in gating',
    },
]

// Plain tile grid instead of LemonSegmentedButton — segmented buttons assume
// equal-width single-line content, which warped the multi-line stat tiles
// and misaligned numbers across columns. A bordered grid keeps numbers and
// labels on consistent baselines.
export function SnapshotStatRow({
    counts,
    frequentlyToleratedCount,
    preset,
    onChange,
}: {
    counts: Record<StatPreset, number>
    // Inline trust-debt indicator on the Tolerated tile — the count of
    // identifiers tolerated ≥3 times in the last 90d. Surfaced as a small
    // chip rather than its own slice.
    frequentlyToleratedCount: number
    preset: StatPreset
    onChange: (next: StatPreset) => void
}): JSX.Element {
    return (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {STATS.map((s) => {
                const active = preset === s.value
                return (
                    <button
                        key={s.value}
                        type="button"
                        aria-pressed={active}
                        onClick={() => onChange(s.value)}
                        className={`text-left border rounded p-3 transition-colors flex flex-col gap-1 ${
                            active
                                ? 'border-primary-3000 bg-primary-3000-button-bg'
                                : 'border-border bg-bg-light hover:border-primary-3000-hover'
                        }`}
                    >
                        <div className="text-2xl font-semibold leading-none tabular-nums">
                            {counts[s.value].toLocaleString()}
                        </div>
                        <div className="flex items-center gap-1.5 text-xs font-semibold mt-1">
                            {s.value !== 'all' && (
                                <>
                                    <span
                                        className="w-2 h-2 rounded-full shrink-0"
                                        style={{ backgroundColor: COLOR_BY_PRESET[s.value] }}
                                    />
                                </>
                            )}
                            <span className="truncate">{s.label}</span>
                            {s.value === 'tolerated_drift' && frequentlyToleratedCount > 0 && (
                                <span className="ml-auto bg-primary-3000-button-bg text-primary-3000 text-[10px] font-semibold rounded px-1.5 py-0.5 shrink-0">
                                    {frequentlyToleratedCount} frequent
                                </span>
                            )}
                        </div>
                        <div className="text-[11px] text-muted leading-tight">{s.description}</div>
                    </button>
                )
            })}
        </div>
    )
}
