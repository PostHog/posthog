import { LemonSegmentedButton } from '@posthog/lemon-ui'

export type StatPreset = 'all' | 'recently_tolerated' | 'frequently_tolerated' | 'currently_quarantined'

const COLOR_BY_PRESET: Record<StatPreset, string> = {
    all: 'var(--text-tertiary)',
    recently_tolerated: 'var(--primary-3000)',
    frequently_tolerated: 'var(--primary-3000)',
    currently_quarantined: 'var(--warning-dark)',
}

const STATS: Array<{ value: StatPreset; label: string; description: string }> = [
    { value: 'all', label: 'All snapshots', description: 'Every baseline image' },
    { value: 'recently_tolerated', label: 'Recently tolerated', description: 'Any tolerate in last 30 days' },
    {
        value: 'frequently_tolerated',
        label: 'Frequently tolerated',
        description: '≥ 3 tolerates in last 90 days · trust debt',
    },
    {
        value: 'currently_quarantined',
        label: 'Currently quarantined',
        description: 'Marked unreliable — skipped in gating',
    },
]

export function SnapshotStatRow({
    counts,
    preset,
    onChange,
}: {
    counts: Record<StatPreset, number>
    preset: StatPreset
    onChange: (next: StatPreset) => void
}): JSX.Element {
    return (
        <LemonSegmentedButton
            fullWidth
            size="large"
            value={preset}
            onChange={(value: string) => onChange(value as StatPreset)}
            options={STATS.map((s) => ({
                value: s.value,
                label: (
                    <div className="flex flex-col items-start gap-0.5 py-1 min-w-0 w-full">
                        <div className="text-2xl font-semibold leading-tight">{counts[s.value].toLocaleString()}</div>
                        <div className="flex items-center gap-1.5 text-xs font-semibold whitespace-nowrap">
                            <span
                                className="w-2 h-2 rounded-full"
                                style={{ backgroundColor: COLOR_BY_PRESET[s.value] }}
                            />
                            {s.label}
                        </div>
                        <div className="text-[11px] text-muted whitespace-normal text-left leading-tight">
                            {s.description}
                        </div>
                    </div>
                ),
            }))}
        />
    )
}
