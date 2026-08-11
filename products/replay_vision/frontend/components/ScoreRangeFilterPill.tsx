import { LemonButton, LemonButtonWithDropdown, LemonInput } from '@posthog/lemon-ui'

/** Compact summary for the pill face, so an active range is readable without opening the dropdown. */
export function scoreRangeLabel(min: number | null, max: number | null): string {
    if (min !== null && max !== null) {
        return `Score ${min} to ${max}`
    }
    if (min !== null) {
        return `Score ≥ ${min}`
    }
    if (max !== null) {
        return `Score ≤ ${max}`
    }
    return 'Score'
}

/** LemonInput type="number" reports an empty field as NaN, so treat anything non-finite as unset. */
export function toScoreBound(raw: number | undefined): number | null {
    return typeof raw === 'number' && Number.isFinite(raw) ? raw : null
}

/**
 * Bounds filter for a scorer's numeric result. Two open-ended inputs rather than an operator
 * dropdown, because that covers "at least", "at most", and a range without a mode to pick first.
 */
export function ScoreRangeFilterPill({
    min,
    max,
    scaleMin,
    scaleMax,
    onChange,
}: {
    min: number | null
    max: number | null
    /** The scanner's configured scale, used as input bounds and as placeholder hints. */
    scaleMin?: number
    scaleMax?: number
    onChange: (min: number | null, max: number | null) => void
}): JSX.Element {
    return (
        <LemonButtonWithDropdown
            type="secondary"
            size="small"
            data-attr="vision-observations-score-filter"
            dropdown={{
                closeOnClickInside: false,
                overlay: (
                    <div className="p-2 w-56 flex flex-col gap-2">
                        <div className="flex items-center gap-2">
                            <span className="text-muted text-xs w-16">At least</span>
                            <LemonInput
                                type="number"
                                size="small"
                                min={scaleMin}
                                max={scaleMax}
                                placeholder={scaleMin !== undefined ? String(scaleMin) : undefined}
                                value={min ?? undefined}
                                onChange={(value) => onChange(toScoreBound(value), max)}
                                className="flex-1"
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-muted text-xs w-16">At most</span>
                            <LemonInput
                                type="number"
                                size="small"
                                min={scaleMin}
                                max={scaleMax}
                                placeholder={scaleMax !== undefined ? String(scaleMax) : undefined}
                                value={max ?? undefined}
                                onChange={(value) => onChange(min, toScoreBound(value))}
                                className="flex-1"
                            />
                        </div>
                        <LemonButton
                            size="small"
                            fullWidth
                            center
                            onClick={() => onChange(null, null)}
                            disabledReason={min === null && max === null ? 'No score filter set' : undefined}
                        >
                            Clear
                        </LemonButton>
                    </div>
                ),
            }}
        >
            {scoreRangeLabel(min, max)}
        </LemonButtonWithDropdown>
    )
}
