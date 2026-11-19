import { IconPerson } from '@posthog/icons'
import type { LemonSelectOption } from '@posthog/lemon-ui'

import type { ChoiceOption } from './repositoryChoices'

/** Select options where a value of your own carries the person icon, so the select needs no separate "you" tag. */
export function withYouIcons<T extends string>(options: ChoiceOption<T>[]): LemonSelectOption<T>[] {
    return options.map(({ mine, ...option }) => ({ ...option, icon: mine ? <IconPerson /> : undefined }))
}
