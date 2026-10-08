import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSelect, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ScoutTrialSetupApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutTrialVariant } from './scoutTrialUtils'

export interface ScoutTrialVariantEditorProps {
    variant: ScoutTrialVariant
    index?: number
    setup: ScoutTrialSetupApi
    locked: boolean
    removable: boolean
    update: (update: Partial<ScoutTrialVariant>) => void
    remove: () => void
}

export function ScoutTrialVariantEditor({
    variant,
    index = 0,
    setup,
    locked,
    removable,
    update,
    remove,
}: ScoutTrialVariantEditorProps): JSX.Element {
    const disabledReason = locked ? 'Start a new trial to change its versions.' : undefined
    const efforts = setup.models.find((model) => model.model === variant.model)?.reasoning_efforts ?? []

    return (
        <LemonCard hoverEffect={false} className="min-w-0 overflow-hidden p-0">
            <div className="flex flex-wrap items-center gap-2 border-b bg-surface-secondary px-4 py-3">
                <LemonTag type="muted" className="w-6 justify-center">
                    {String.fromCharCode(65 + index)}
                </LemonTag>
                <span className="min-w-0 flex-1 break-words text-sm font-semibold">
                    {variant.label.trim() || 'Untitled version'}
                </span>
                {index === 0 && <LemonTag type="muted">Baseline</LemonTag>}
                {index > 0 && removable && (
                    <LemonButton
                        icon={<IconTrash />}
                        aria-label={`Remove ${variant.label.trim() || 'untitled version'}`}
                        tooltip="Remove version"
                        size="small"
                        type="tertiary"
                        status="danger"
                        onClick={remove}
                        disabledReason={disabledReason}
                        data-attr="scout-trial-remove-version"
                    />
                )}
            </div>
            <div className="flex flex-col gap-4 p-4">
                <div className="flex flex-wrap items-start gap-3">
                    <LemonField.Pure label="Name" htmlFor={`${variant.id}-name`} className="min-w-48 flex-1 basis-52">
                        <LemonInput
                            id={`${variant.id}-name`}
                            value={variant.label}
                            onChange={(label) => update({ label })}
                            maxLength={80}
                            disabledReason={disabledReason}
                            placeholder="Version name"
                            data-attr="scout-trial-version-name"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Model" className="min-w-48 flex-1 basis-60">
                        <LemonSelect
                            value={variant.model}
                            options={setup.models.map((model) => ({ value: model.model, label: model.model }))}
                            onChange={(model) => {
                                const nextEfforts =
                                    setup.models.find((option) => option.model === model)?.reasoning_efforts ?? []
                                update({
                                    model,
                                    effort: nextEfforts.includes(variant.effort)
                                        ? variant.effort
                                        : (nextEfforts[0] ?? ''),
                                })
                            }}
                            disabledReason={disabledReason}
                            fullWidth
                            menu={{ className: 'ph-no-capture ph-replay-block' }}
                            dropdownMatchSelectWidth
                            truncateText={{ maxWidthClass: 'max-w-full' }}
                            data-attr="scout-trial-version-model"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Effort" className="min-w-28 flex-1 basis-28">
                        <LemonSelect
                            value={variant.effort}
                            options={efforts.map((effort) => ({ value: effort, label: effort }))}
                            onChange={(effort) => update({ effort })}
                            disabledReason={disabledReason}
                            fullWidth
                            data-attr="scout-trial-version-effort"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Prompt" className="min-w-40 flex-1 basis-40">
                        <LemonSegmentedButton
                            value={variant.replacePrompt ? 'custom' : 'current'}
                            options={[
                                { value: 'current', label: 'Current', 'data-attr': 'scout-trial-prompt-current' },
                                { value: 'custom', label: 'Custom', 'data-attr': 'scout-trial-prompt-custom' },
                            ]}
                            onChange={(value) =>
                                update({
                                    replacePrompt: value === 'custom',
                                    prompt: value === 'custom' && !variant.prompt ? setup.skill_body : variant.prompt,
                                })
                            }
                            disabledReason={disabledReason}
                            fullWidth
                        />
                    </LemonField.Pure>
                </div>
                {variant.replacePrompt && (
                    <LemonField.Pure
                        label="Custom prompt"
                        htmlFor={`${variant.id}-prompt`}
                        help="Replaces the scout's prompt for this version only. Files and tool access stay the same."
                    >
                        <LemonTextArea
                            id={`${variant.id}-prompt`}
                            value={variant.prompt}
                            onChange={(prompt) => update({ prompt })}
                            minRows={4}
                            maxRows={18}
                            maxLength={100000}
                            disabled={locked}
                            placeholder="Write the full prompt for this version…"
                            data-attr="scout-trial-custom-prompt"
                        />
                    </LemonField.Pure>
                )}
            </div>
        </LemonCard>
    )
}
