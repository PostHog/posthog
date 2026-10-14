import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { HogFunctionStatusTag } from 'scenes/hog-functions/misc/HogFunctionStatusTag'

import { StepCatalogEntry } from './stepCatalog'
import { StepPickerFavoriteToggle } from './StepPickerFavoriteToggle'
import { stepPickerLogic } from './stepPickerLogic'
import { stepTitle } from './stepPickerPresentation'
import { StepPickerStepIcon } from './StepPickerStepIcon'

export function StepPickerStepRow({ entry, subtitle }: { entry: StepCatalogEntry; subtitle: string }): JSX.Element {
    const { selectedStepId } = useValues(stepPickerLogic)
    const { selectStep, pickStep } = useActions(stepPickerLogic)

    return (
        <li className="group flex min-w-0 items-center gap-1 [&>.LemonButton]:min-w-0 [&>.LemonButton]:shrink">
            <LemonButton
                fullWidth
                active={selectedStepId === entry.id}
                icon={<StepPickerStepIcon entry={entry} size="md" />}
                onClick={() => selectStep(entry.id)}
                data-attr="workflow-step-picker-step"
            >
                <span className="flex min-w-0 flex-1 flex-col">
                    <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate" data-attr="workflow-step-picker-step-title">
                            {stepTitle(entry)}
                        </span>
                        {entry.status ? <HogFunctionStatusTag status={entry.status} /> : null}
                    </span>
                    <span className="truncate text-xs font-normal text-secondary">{subtitle}</span>
                </span>
            </LemonButton>
            <span className="flex opacity-0 group-hover:opacity-100 focus-within:opacity-100 @max-[44rem]/step-picker:opacity-100">
                <StepPickerFavoriteToggle entry={entry} iconOnly />
                <LemonButton
                    size="small"
                    icon={<IconPlus />}
                    tooltip="Add step"
                    aria-label="Add step"
                    onClick={() => pickStep(entry, 'row')}
                    data-attr="workflow-step-picker-row-add"
                />
            </span>
        </li>
    )
}
