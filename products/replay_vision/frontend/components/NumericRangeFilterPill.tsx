import { LemonButton, LemonButtonWithDropdown, LemonInput } from '@posthog/lemon-ui'

/** Compact summary for the pill face, so an active range is readable without opening the dropdown. */
export function numericRangeLabel(label: string, min: number | null, max: number | null): string {
    if (min !== null && max !== null) {
        return `${label} ${min} to ${max}`
    }
    if (min !== null) {
        return `${label} ≥ ${min}`
    }
    if (max !== null) {
        return `${label} ≤ ${max}`
    }
    return label
}

/** LemonInput type="number" reports an empty field as NaN, so treat anything non-finite as unset. */
export function toNumericBound(raw: number | undefined): number | null {
    return typeof raw === 'number' && Number.isFinite(raw) ? raw : null
}

/**
 * Bounds filter for a numeric observation field. Two open-ended inputs rather than an operator
 * dropdown, because that covers "at least", "at most", and a range without a mode to pick first.
 */
export function NumericRangeFilterPill({
    label,
    min,
    max,
    scaleMin,
    scaleMax,
    onChange,
    dataAttr,
}: {
    label: string
    min: number | null
    max: number | null
    /** The field's configured scale, used as input bounds and as placeholder hints. */
    scaleMin?: number
    scaleMax?: number
    onChange: (min: number | null, max: number | null) => void
    dataAttr?: string
}): JSX.Element {
    return (
        <LemonButtonWithDropdown
            type="secondary"
            size="small"
            data-attr={dataAttr}
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
                                value={min ?? NaN}
                                onChange={(value) => onChange(toNumericBound(value), max)}
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
                                value={max ?? NaN}
                                onChange={(value) => onChange(min, toNumericBound(value))}
                                className="flex-1"
                            />
                        </div>
                        <LemonButton
                            size="small"
                            fullWidth
                            center
                            onClick={() => onChange(null, null)}
                            disabledReason={
                                min === null && max === null ? `No ${label.toLowerCase()} filter set` : undefined
                            }
                        >
                            Clear
                        </LemonButton>
                    </div>
                ),
            }}
        >
            {numericRangeLabel(label, min, max)}
        </LemonButtonWithDropdown>
    )
}
