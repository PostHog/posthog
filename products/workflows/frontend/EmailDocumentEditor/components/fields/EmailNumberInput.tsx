import { useState } from 'react'

import { LemonInput, LemonInputPropsNumber } from '@posthog/lemon-ui'

import { NumberLimit, clampNumber } from './numberLimits'
import { numberOrUnset } from './numberOrUnset'

/**
 * A number input that only hands over numbers inside its limits. A number outside them stays a draft while it's typed,
 * because it can be on the way to a valid one, and becomes the nearest limit when the person leaves the field. A saved
 * number outside them shows as it is and stays until someone types another one.
 */
export function EmailNumberInput({
    value,
    limit,
    unit = 'px',
    onChange,
    ...props
}: Omit<
    LemonInputPropsNumber,
    'type' | 'value' | 'onChange' | 'min' | 'max' | 'step' | 'onFocus' | 'onBlur' | 'onPressEnter'
> & {
    value: number | undefined
    limit: NumberLimit
    unit?: string
    onChange: (value: number | undefined) => void
}): JSX.Element {
    const [draft, setDraft] = useState<number | null>(null)
    const [corrected, setCorrected] = useState<number | null>(null)
    const shown = draft ?? value
    const outside = shown !== undefined && clampNumber(shown, limit) !== shown

    const finish = (): void => {
        if (draft === null) {
            return
        }
        const allowed = clampNumber(draft, limit)
        setDraft(null)
        setCorrected(allowed)
        onChange(allowed)
    }
    const atLimit = draft !== null ? clampNumber(draft, limit) : corrected === value ? corrected : null

    const end = atLimit === limit.max ? 'maximum' : 'minimum'

    return (
        <div
            className="flex-1 min-w-0 flex flex-col"
            // Escape closes the fullscreen editor, which takes the field away without a blur.
            onKeyDown={(event) => event.key === 'Escape' && finish()}
        >
            <LemonInput
                {...props}
                type="number"
                size="small"
                // The host form checks these before it submits, and a saved number outside them must not block a save.
                min={outside ? undefined : limit.min}
                max={outside ? undefined : limit.max}
                step="any"
                // An empty string keeps the input controlled while it shows the placeholder.
                value={shown ?? ('' as unknown as number)}
                onChange={(next) => {
                    const number = numberOrUnset(next)
                    const allowed = number === undefined || number === clampNumber(number, limit)
                    setCorrected(null)
                    setDraft(allowed ? null : number)
                    if (allowed) {
                        onChange(number)
                    }
                }}
                onFocus={() => setCorrected(null)}
                onBlur={finish}
                onPressEnter={finish}
            />
            {atLimit !== null ? (
                <span role="status" className="text-xxs text-secondary">
                    {draft === null ? `Set to the ${end}: ` : `${end === 'maximum' ? 'Maximum' : 'Minimum'}: `}
                    {atLimit}
                    {unit}
                </span>
            ) : null}
        </div>
    )
}
