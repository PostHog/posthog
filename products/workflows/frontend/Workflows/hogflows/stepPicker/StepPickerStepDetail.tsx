import { useActions } from 'kea'

import { IconLogomark, IconPlus } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { HogFunctionStatusTag } from 'scenes/hog-functions/misc/HogFunctionStatusTag'

import { StepCatalogEntry } from './stepCatalog'
import { StepPickerFavoriteToggle } from './StepPickerFavoriteToggle'
import { stepPickerLogic } from './stepPickerLogic'
import { STEP_CATEGORY_LABELS, providerLabelOf, stepTitle } from './stepPickerPresentation'
import { StepPickerStepIcon } from './StepPickerStepIcon'

export function StepPickerStepDetail({ entry }: { entry: StepCatalogEntry }): JSX.Element {
    const { pickStep } = useActions(stepPickerLogic)

    return (
        <div className="flex flex-col gap-3 p-4">
            <div className="flex min-w-0 items-center gap-3">
                <StepPickerStepIcon entry={entry} size="lg" />
                <div className="min-w-0">
                    <div className="truncate text-base font-semibold">{stepTitle(entry)}</div>
                    <div className="truncate text-xs text-secondary">{providerLabelOf(entry)}</div>
                </div>
            </div>
            {entry.description ? <p className="m-0 text-sm">{entry.description}</p> : null}
            <div className="flex flex-wrap gap-1">
                {entry.origin === 'posthog' ? (
                    <LemonTag type="highlight" icon={<IconLogomark />}>
                        {providerLabelOf(entry)}
                    </LemonTag>
                ) : (
                    <LemonTag type="muted">Third party</LemonTag>
                )}
                {entry.category ? <LemonTag type="default">{STEP_CATEGORY_LABELS[entry.category]}</LemonTag> : null}
                {entry.status ? <HogFunctionStatusTag status={entry.status} /> : null}
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => pickStep(entry, 'detail')}
                    data-attr="workflow-step-picker-add-step"
                >
                    Add step
                </LemonButton>
                <StepPickerFavoriteToggle entry={entry} />
            </div>
        </div>
    )
}
