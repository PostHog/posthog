import type { LemonSelectOption } from '@posthog/lemon-ui'

import { ScoutModelPinEnumApi } from 'products/signals/frontend/generated/api.schemas'

export type ScoutModelPinValue = ScoutModelPinEnumApi | null

/**
 * How each pinnable model is described in the picker. The ids come from the generated enum, which
 * the scout config serializer's allowlist produces, so a model added there still gets an option
 * here. It just falls back to showing its raw id until someone writes it a label.
 */
const SCOUT_MODEL_LABELS: Partial<Record<ScoutModelPinEnumApi, string>> = {
    [ScoutModelPinEnumApi.Gpt56Luna]: 'Fast',
    [ScoutModelPinEnumApi.Gpt56Terra]: 'Balanced',
    [ScoutModelPinEnumApi.Gpt56Sol]: 'Most capable',
}

function modelOption(model: ScoutModelPinEnumApi): LemonSelectOption<ScoutModelPinValue> {
    const label = SCOUT_MODEL_LABELS[model]
    return {
        value: model,
        label: label ?? model,
        labelInMenu: (
            <div className="flex flex-col">
                <span>{label ?? model}</span>
                {label ? <span className="text-[11.5px] text-muted">{model}</span> : null}
            </div>
        ),
    }
}

/** The stored pin as a picker value. Anything not on the allowlist still has to round-trip. */
export function toScoutModelPinValue(storedModel: string | null | undefined): ScoutModelPinValue {
    return (storedModel || null) as ScoutModelPinValue
}

/**
 * Options for the per-scout model picker: "Default" first, then the models a pin may name.
 *
 * A stored pin that is not on the allowlist is appended as its own option, so a scout pinned
 * before the list narrowed keeps showing what it actually runs on instead of reading as "Default".
 */
export function getScoutModelOptions(storedModel: string | null | undefined): LemonSelectOption<ScoutModelPinValue>[] {
    const allowed = Object.values(ScoutModelPinEnumApi)
    const stored = toScoutModelPinValue(storedModel)
    return [
        {
            value: null,
            label: 'Default',
            labelInMenu: (
                <div className="flex flex-col">
                    <span>Default</span>
                    <span className="text-[11.5px] text-muted">PostHog picks the model</span>
                </div>
            ),
        },
        ...allowed.map(modelOption),
        ...(stored && !allowed.includes(stored) ? [modelOption(stored)] : []),
    ]
}
