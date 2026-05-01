// Faceted sidebar for the snapshots overview. Three groups (TYPE / AREA /
// STABILITY), each a flat column of `<button>` rows. Counts are pre-computed
// by the scene logic so this stays purely presentational.

export type FacetBucket = { value: string; label: string; count: number }

export type FacetGroups = {
    type: FacetBucket[]
    area: FacetBucket[]
    stability: FacetBucket[]
}

export type FacetSelection = {
    type: Set<string>
    area: Set<string>
    stability: Set<string>
}

// Stability first — it's the most actionable facet for the page's primary use
// case ("which snapshots am I tolerating drift on?"). Type and Area are
// context refinements after that.
const GROUP_LABELS: Array<{ key: keyof FacetGroups; label: string }> = [
    { key: 'stability', label: 'Stability' },
    { key: 'type', label: 'Type' },
    { key: 'area', label: 'Area' },
]

export function SnapshotFacetSidebar({
    groups,
    selection,
    onToggle,
}: {
    groups: FacetGroups
    selection: FacetSelection
    onToggle: (group: keyof FacetGroups, value: string) => void
}): JSX.Element {
    return (
        <aside className="w-52 shrink-0 flex flex-col gap-4 text-sm">
            {GROUP_LABELS.map(({ key, label }) => {
                const buckets = groups[key]
                if (!buckets.length) {
                    return null
                }
                const sel = selection[key]
                return (
                    <div key={key} className="flex flex-col gap-0.5">
                        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-tertiary mb-1 mt-0">
                            {label}
                        </h4>
                        {buckets.map((bucket) => {
                            const active = sel.has(bucket.value)
                            return (
                                <button
                                    key={bucket.value}
                                    type="button"
                                    aria-pressed={active}
                                    onClick={() => onToggle(key, bucket.value)}
                                    className={`flex items-center justify-between gap-2 px-2 py-1 rounded text-xs text-left transition-colors ${
                                        active
                                            ? 'bg-primary-3000-button-bg text-primary-3000-button-fg font-medium'
                                            : 'hover:bg-primary-highlight'
                                    }`}
                                >
                                    <span className="truncate">{bucket.label}</span>
                                    <span className="text-muted tabular-nums shrink-0">
                                        {bucket.count.toLocaleString()}
                                    </span>
                                </button>
                            )
                        })}
                    </div>
                )
            })}
        </aside>
    )
}
