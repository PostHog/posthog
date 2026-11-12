import { IconLock } from '@posthog/icons'
import { LemonSelectOption, LemonSelectSection } from '@posthog/lemon-ui'

import { retentionPeriodLabel } from 'lib/utils/retentionPeriodLabel'

export interface EventsRetentionPeriodChoices {
    defaultLabel: string
    defaultMonths: number
    choices: readonly number[]
    minMonths: number
    maxMonths: number
    planMonths: number
    dataAttr: string
}

function choiceOption(
    months: number,
    { minMonths, maxMonths, planMonths, dataAttr }: EventsRetentionPeriodChoices
): LemonSelectOption<number | null> {
    const option = { value: months, label: retentionPeriodLabel(months), 'data-attr': `${dataAttr}-option-${months}` }
    if (months > planMonths) {
        return {
            ...option,
            labelInMenu: (
                <span className="flex flex-1 items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                        <IconLock />
                        {option.label}
                    </span>
                    <span className="text-xs text-secondary">Upgrade</span>
                </span>
            ),
            disabledReason: `Your plan keeps events for up to ${retentionPeriodLabel(planMonths)}. Upgrade your plan to keep them longer.`,
        }
    }
    if (months < minMonths || months > maxMonths) {
        return {
            ...option,
            disabledReason: `This organization can keep events for ${retentionPeriodLabel(minMonths)} to ${retentionPeriodLabel(maxMonths)}. Contact PostHog support to change this.`,
        }
    }
    return option
}

export function eventsRetentionPeriodOptions(
    choices: EventsRetentionPeriodChoices
): LemonSelectSection<number | null>[] {
    return [
        {
            options: [
                {
                    value: null,
                    label: `${choices.defaultLabel} (${retentionPeriodLabel(choices.defaultMonths)})`,
                    'data-attr': `${choices.dataAttr}-option-default`,
                },
            ],
        },
        { options: choices.choices.map((months) => choiceOption(months, choices)) },
    ]
}
