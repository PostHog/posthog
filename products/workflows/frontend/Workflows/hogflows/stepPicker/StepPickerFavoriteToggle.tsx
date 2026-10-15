import { useActions, useValues } from 'kea'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { StepCatalogEntry } from './stepCatalog'
import { stepPickerLogic } from './stepPickerLogic'

export function StepPickerFavoriteToggle({
    entry,
    iconOnly = false,
}: {
    entry: StepCatalogEntry
    iconOnly?: boolean
}): JSX.Element {
    const { favoriteStepIds } = useValues(stepPickerLogic)
    const { toggleFavorite } = useActions(stepPickerLogic)
    const isFavorite = favoriteStepIds.includes(entry.id)
    const label = isFavorite ? 'Remove from favorites' : 'Add to favorites'

    return (
        <LemonButton
            type={iconOnly ? 'tertiary' : 'secondary'}
            size={iconOnly ? 'small' : undefined}
            icon={isFavorite ? <IconStarFilled className="text-warning" /> : <IconStar />}
            tooltip={iconOnly ? label : undefined}
            aria-label={iconOnly ? label : undefined}
            onClick={() => toggleFavorite(entry)}
            data-attr="workflow-step-picker-favorite"
        >
            {iconOnly ? null : label}
        </LemonButton>
    )
}
