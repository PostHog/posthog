export type FlakinessPreset = 'needs_decision' | 'broken' | 'unstable' | 'at_risk' | 'quiet' | 'quarantined'

// Mirrors `FLAKINESS_RATE_DAYS` in
// `products/visual_review/backend/facade/contracts.py`. Keep in sync, because
// the backend value is the rate denominator and this constant drives the copy.
export const FLAKE_RATE_DAYS = 7

const COLOR_BY_PRESET: Record<FlakinessPreset, string> = {
    needs_decision: 'var(--primary-3000)',
    broken: 'var(--danger)',
    unstable: 'var(--warning-dark)',
    at_risk: 'var(--warning)',
    quiet: 'var(--muted)',
    quarantined: 'var(--brand-blue)',
}

const STATS: Array<{ value: FlakinessPreset; label: string; description: string }> = [
    {
        value: 'needs_decision',
        label: 'Needs a decision',
        description: 'Quarantine ran out, or nothing has failed under it recently',
    },
    {
        value: 'broken',
        label: 'Broken',
        description: 'Fails nearly every run, so its baseline is wrong or missing',
    },
    {
        value: 'unstable',
        label: 'Unstable',
        description: 'Fails some runs and not others',
    },
    {
        value: 'at_risk',
        label: 'At risk',
        description: 'Passes, but its diff is already close to the threshold',
    },
    {
        value: 'quiet',
        label: 'Quiet',
        description: 'Absorbed with room to spare, or nothing failing now',
    },
    {
        value: 'quarantined',
        label: 'Quarantined',
        description: 'Skipped when a run decides pass or fail',
    },
]

interface FlakinessStatRowProps {
    counts: Record<FlakinessPreset, number>
    preset: FlakinessPreset
    onChange: (next: FlakinessPreset) => void
}

/**
 * The six populations this scene can show, ordered by how much attention each
 * one wants.
 *
 * Together they have to cover every listed row. `quiet` is the catch-all that
 * makes that hold: it takes both `noisy` and `clean`, because a row can be
 * listed for history the rate span no longer counts and would otherwise show
 * in the totals while no tile could reach it. The State column still names the
 * precise state, so nothing is lost by grouping them here.
 *
 * There is still no "all snapshots" tile: that would repeat the Snapshots tab
 * and open thousands of rows with nothing to act on.
 */
export function FlakinessStatRow({ counts, preset, onChange }: FlakinessStatRowProps): JSX.Element {
    return (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-2">
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
