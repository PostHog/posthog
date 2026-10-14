import { useActions, useValues } from 'kea'

import { IconLogomark } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { stepPickerLogic } from './stepPickerLogic'
import { STEP_PRODUCT_DESCRIPTIONS, StepProvider, stepCountLabel, stepTitle } from './stepPickerPresentation'
import { StepPickerProviderIcon } from './StepPickerProviderIcon'
import { StepPickerStepIcon } from './StepPickerStepIcon'

export function StepPickerProviderDetail({ provider }: { provider: StepProvider }): JSX.Element {
    const { selectedStepId } = useValues(stepPickerLogic)
    const { selectStep } = useActions(stepPickerLogic)

    return (
        <div className="flex flex-col gap-3 p-4">
            <div className="flex min-w-0 items-center gap-3">
                <StepPickerProviderIcon provider={provider} size="lg" />
                <div className="min-w-0">
                    <div className="truncate text-base font-semibold">{provider.label}</div>
                    <div className="text-xs text-secondary">{stepCountLabel(provider.entries.length)}</div>
                </div>
            </div>
            {provider.product ? (
                <p className="m-0 text-sm text-secondary">{STEP_PRODUCT_DESCRIPTIONS[provider.product]}</p>
            ) : null}
            <div className="flex flex-wrap gap-1">
                {provider.product ? (
                    <LemonTag type="highlight" icon={<IconLogomark />}>
                        {provider.label}
                    </LemonTag>
                ) : (
                    <LemonTag type="muted">Third party</LemonTag>
                )}
            </div>
            <div className="flex flex-col rounded border p-1">
                {provider.entries.map((entry) => (
                    <LemonButton
                        key={entry.id}
                        fullWidth
                        active={selectedStepId === entry.id}
                        icon={<StepPickerStepIcon entry={entry} size="md" />}
                        onClick={() => selectStep(entry.id)}
                    >
                        <span className="flex min-w-0 flex-1 flex-col">
                            <span className="truncate">{stepTitle(entry)}</span>
                            <span className="truncate text-xs font-normal text-secondary">{entry.description}</span>
                        </span>
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
