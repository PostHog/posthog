import { useEffect, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Label } from 'lib/ui/Label/Label'
import {
    MINIMUM_DETECTABLE_EFFECT_MAX,
    MINIMUM_DETECTABLE_EFFECT_MIN,
} from 'scenes/experiments/RunningTimeCalculator/calculations'

export interface MinimumDetectableEffectFieldProps {
    value: number
    onChange: (value: number) => void
}

const isInRange = (value: number | undefined): value is number =>
    value !== undefined && value >= MINIMUM_DETECTABLE_EFFECT_MIN && value <= MINIMUM_DETECTABLE_EFFECT_MAX

export function MinimumDetectableEffectField({ value, onChange }: MinimumDetectableEffectFieldProps): JSX.Element {
    // The input keeps what the user types, so that an empty field or a partial number stays editable. Only a value in
    // range reaches the estimate.
    const [draft, setDraft] = useState<number | undefined>(value)
    useEffect(() => setDraft(value), [value])

    const isDraftEmpty = draft === undefined || Number.isNaN(draft)

    const commitDraft = (): void => {
        if (draft === undefined || Number.isNaN(draft)) {
            setDraft(value)
        } else if (!isInRange(draft)) {
            const clamped = Math.min(MINIMUM_DETECTABLE_EFFECT_MAX, Math.max(MINIMUM_DETECTABLE_EFFECT_MIN, draft))
            setDraft(clamped)
            onChange(clamped)
        }
    }

    return (
        <div>
            <Label intent="menu">Minimum detectable effect</Label>
            <div className="flex items-center gap-3">
                <div className="flex-[3]">
                    <LemonSlider
                        value={value}
                        onChange={onChange}
                        min={MINIMUM_DETECTABLE_EFFECT_MIN}
                        max={MINIMUM_DETECTABLE_EFFECT_MAX}
                        step={1}
                    />
                </div>
                <div className="flex-1 flex items-center gap-1">
                    <LemonInput
                        type="number"
                        value={draft}
                        onChange={(next) => {
                            setDraft(next)
                            if (isInRange(next)) {
                                onChange(next)
                            }
                        }}
                        onBlur={commitDraft}
                        onPressEnter={commitDraft}
                        status={isDraftEmpty || isInRange(draft) ? 'default' : 'danger'}
                        min={MINIMUM_DETECTABLE_EFFECT_MIN}
                        max={MINIMUM_DETECTABLE_EFFECT_MAX}
                        step={1}
                        className="flex-1"
                        data-attr="experiment-running-time-mde-input"
                    />
                    <span className="text-muted">%</span>
                </div>
            </div>
            {!isDraftEmpty && !isInRange(draft) && (
                <div className="text-xs text-danger mt-1">
                    {`Enter a value from ${MINIMUM_DETECTABLE_EFFECT_MIN} to ${MINIMUM_DETECTABLE_EFFECT_MAX}.`}
                </div>
            )}
        </div>
    )
}
