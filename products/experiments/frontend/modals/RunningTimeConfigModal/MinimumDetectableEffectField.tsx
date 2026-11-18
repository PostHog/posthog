import { LemonInput } from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Label } from 'lib/ui/Label/Label'
import {
    MINIMUM_DETECTABLE_EFFECT_MAX,
    MINIMUM_DETECTABLE_EFFECT_MIN,
} from 'scenes/experiments/RunningTimeCalculator/calculations'

import { MINIMUM_DETECTABLE_EFFECT_RANGE_ERROR, useMinimumDetectableEffectDraft } from './runningTimeConfigModel'

export interface MinimumDetectableEffectFieldProps {
    value: number
    onChange: (value: number) => void
}

export function MinimumDetectableEffectField({ value, onChange }: MinimumDetectableEffectFieldProps): JSX.Element {
    const { draft, setDraftValue, commitDraft, outOfRange } = useMinimumDetectableEffectDraft(value, onChange)

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
                        onChange={setDraftValue}
                        onBlur={commitDraft}
                        onPressEnter={commitDraft}
                        status={outOfRange ? 'danger' : 'default'}
                        min={MINIMUM_DETECTABLE_EFFECT_MIN}
                        max={MINIMUM_DETECTABLE_EFFECT_MAX}
                        step={1}
                        className="flex-1"
                        data-attr="experiment-running-time-mde-input"
                    />
                    <span className="text-muted">%</span>
                </div>
            </div>
            {outOfRange && <div className="text-xs text-danger mt-1">{MINIMUM_DETECTABLE_EFFECT_RANGE_ERROR}</div>}
        </div>
    )
}
