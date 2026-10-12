import { LemonSelect } from '@posthog/lemon-ui'

import type {
    AutomaticFlashForEnumApi,
    ReviewRepositoryPersonApi,
    ReviewRepositoryPersonKindEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { PeopleList } from './PeopleList'
import { FLASH_FOR_OPTIONS, peopleKindFor } from './repositoryChoices'

/** Who gets automatic reviews, for the project settings and for a repository exception alike. */
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
    const peopleList = kind && (
        <PeopleList
            kind={kind}
            people={people}
            canEdit={canEdit}
            disabledReason={disabledReason}
            onAdd={(userId) => onAddPerson(userId, kind)}
            onRemove={onRemovePerson}
        />
    )
    return (
        // The except list continues the "for everyone" sentence, so it shares the select's line.
        <div className={kind === 'excepted' ? 'flex flex-wrap items-center gap-1.5' : 'flex flex-col gap-1.5'}>
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
            {/* A separate item, so a wrapped except list never starts its line with the comma. */}
            {kind === 'excepted' && <span className="-ml-1 text-xs text-secondary">,</span>}
            {peopleList}
        </div>
    )
}
