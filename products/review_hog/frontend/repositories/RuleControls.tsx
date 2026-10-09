import { LemonSelect } from '@posthog/lemon-ui'

import type {
    AutomaticFlashForEnumApi,
    ReviewRepositoryPersonApi,
    ReviewRepositoryPersonKindEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { PeopleList } from './PeopleList'
import { FLASH_FOR_OPTIONS, peopleKindFor } from './repositoryChoices'

/** Who gets automatic Flash, for the project settings and for a repository exception alike. */
export function RuleControls({
    label,
    flashFor,
    people,
    canEdit,
    disabledReason,
    onChangeFlashFor,
    onAddPerson,
    onRemovePerson,
    dataAttr,
}: {
    label: string
    flashFor: AutomaticFlashForEnumApi
    people: readonly ReviewRepositoryPersonApi[]
    canEdit: boolean
    disabledReason?: string
    onChangeFlashFor: (flashFor: AutomaticFlashForEnumApi) => void
    onAddPerson: (userId: number, kind: ReviewRepositoryPersonKindEnumApi) => void
    onRemovePerson: (person: ReviewRepositoryPersonApi) => void
    dataAttr: string
}): JSX.Element {
    const kind = peopleKindFor(flashFor)
    return (
        <div className="flex flex-col gap-1.5">
            <LemonSelect
                size="small"
                aria-label={label}
                value={flashFor}
                options={FLASH_FOR_OPTIONS}
                onChange={(value) => value !== flashFor && onChangeFlashFor(value)}
                disabledReason={disabledReason}
                data-attr={dataAttr}
                className="max-w-full self-start"
            />
            {kind && (
                <PeopleList
                    kind={kind}
                    people={people}
                    canEdit={canEdit}
                    disabledReason={disabledReason}
                    onAdd={(userId) => onAddPerson(userId, kind)}
                    onRemove={onRemovePerson}
                />
            )}
        </div>
    )
}
