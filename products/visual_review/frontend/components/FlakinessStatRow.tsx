export type FlakinessPreset = 'unstable' | 'settled' | 'quarantined' | 'needs_decision'

// Mirrors `FLAKINESS_RECENT_DAYS` in
// `products/visual_review/backend/facade/contracts.py`. Keep in sync, because
// the backend value decides `flakiness_state` and this constant drives the copy.
export const RECENT_VARIANT_WINDOW_DAYS = 7

const COLOR_BY_PRESET: Record<FlakinessPreset, string> = {
    unstable: 'var(--danger)',
    settled: 'var(--warning-dark)',
    quarantined: 'var(--warning)',
    needs_decision: 'var(--primary-3000)',
}

const STATS: Array<{ value: FlakinessPreset; label: string; description: string }> = [
    {
        value: 'unstable',
        label: 'Unstable',
        description: `Rendered a variant in the last ${RECENT_VARIANT_WINDOW_DAYS} days`,
    },
    {
        value: 'settled',
        label: 'Settled',
        description: 'Carries variants, but has been quiet for longer than that',
    },
    {
        value: 'quarantined',
        label: 'Quarantined',
        description: 'Skipped when a run decides pass or fail',
    },
    {
        value: 'needs_decision',
        label: 'Needs a decision',
        description: 'Quarantine ran out, or has been quiet long enough to lift',
    },
]

interface FlakinessStatRowProps {
    counts: Record<FlakinessPreset, number>
    preset: FlakinessPreset
    onChange: (next: FlakinessPreset) => void
}

/**
 * The four populations this scene can show. Every tile is a filter that lands on
 * a workable list, so there is deliberately no "all snapshots" tile: it would
 * repeat the Snapshots tab and open thousands of rows with nothing to act on.
 */
export function FlakinessStatRow({ counts, preset, onChange }: FlakinessStatRowProps): JSX.Element {
    return (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {STATS.map((stat) => {
                const active = preset === stat.value
                return (
                    <button
                        key={stat.value}
                        type="button"
                        aria-pressed={active}
                        data-attr={`visual-review-flakiness-preset-${stat.value}`}
                        onClick={() => onChange(stat.value)}
                        className={`text-left border rounded p-3 transition-colors flex flex-col gap-1 ${
                            active
                                ? 'border-primary-3000 bg-primary-3000-button-bg'
                                : 'border-border bg-bg-light hover:border-primary-3000-hover'
                        }`}
                    >
                        <div className="text-2xl font-semibold leading-none tabular-nums">
                            {counts[stat.value].toLocaleString()}
                        </div>
                        <div className="flex items-center gap-1.5 text-xs font-semibold mt-1">
                            <span
                                className="w-2 h-2 rounded-full shrink-0"
                                style={{ backgroundColor: COLOR_BY_PRESET[stat.value] }}
                            />
                            <span className="truncate">{stat.label}</span>
                        </div>
                        <div className="text-[11px] text-muted leading-tight">{stat.description}</div>
                    </button>
                )
            })}
        </div>
    )
}
