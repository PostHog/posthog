import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ScoutTrialSetupApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutTrialVariant } from './scoutTrialUtils'

export interface ScoutTrialVariantEditorProps {
    variant: ScoutTrialVariant
    setup: ScoutTrialSetupApi
    locked: boolean
    removable: boolean
    update: (update: Partial<ScoutTrialVariant>) => void
    remove: () => void
}

export function ScoutTrialVariantEditor({
    variant,
    setup,
    locked,
    removable,
    update,
    remove,
}: ScoutTrialVariantEditorProps): JSX.Element {
    const disabledReason = locked ? 'Start a new comparison to change its variants.' : undefined
    const efforts = setup.models.find((model) => model.model === variant.model)?.reasoning_efforts ?? []

    return (
        <LemonCard hoverEffect={false} className="p-3 flex flex-col gap-3 min-w-0">
            <div className="flex items-end gap-2">
                <LemonField.Pure label="Variant name" className="flex-1 min-w-0">
                    <LemonInput
                        value={variant.label}
                        onChange={(label) => update({ label })}
                        maxLength={80}
                        disabledReason={disabledReason}
                    />
                </LemonField.Pure>
                {removable && (
                    <LemonButton
                        icon={<IconTrash />}
                        aria-label="Remove variant"
                        type="tertiary"
                        onClick={remove}
                        disabledReason={disabledReason}
                    />
                )}
            </div>
            <div className="grid grid-cols-1 @2xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-3">
                <LemonField.Pure label="Model">
                    <LemonSelect
                        value={variant.model}
                        options={setup.models.map((model) => ({ value: model.model, label: model.model }))}
                        onChange={(model) => {
                            const nextEfforts =
                                setup.models.find((option) => option.model === model)?.reasoning_efforts ?? []
                            update({
                                model,
                                effort: nextEfforts.includes(variant.effort) ? variant.effort : (nextEfforts[0] ?? ''),
                            })
                        }}
                        disabledReason={disabledReason}
                        fullWidth
                        menu={{ className: 'ph-no-capture ph-replay-block' }}
                        dropdownMatchSelectWidth
                        truncateText={{ maxWidthClass: 'max-w-full' }}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Effort">
                    <LemonSelect
                        value={variant.effort}
                        options={efforts.map((effort) => ({ value: effort, label: effort }))}
                        onChange={(effort) => update({ effort })}
                        disabledReason={disabledReason}
                        fullWidth
                    />
                </LemonField.Pure>
            </div>
            <LemonCheckbox
                label="Use a replacement prompt"
                checked={variant.replacePrompt}
                disabled={locked}
                onChange={(replacePrompt) =>
                    update({
                        replacePrompt,
                        prompt: replacePrompt && !variant.prompt ? setup.skill_body : variant.prompt,
                    })
                }
            />
            {variant.replacePrompt && (
                <LemonField.Pure
                    label="Scout prompt"
                    help="Replaces the skill body for this variant. Supporting files and tool access stay the same."
                >
                    <LemonTextArea
                        value={variant.prompt}
                        onChange={(prompt) => update({ prompt })}
                        minRows={7}
                        maxRows={18}
                        maxLength={100000}
                        disabled={locked}
                    />
                </LemonField.Pure>
            )}
        </LemonCard>
    )
}
