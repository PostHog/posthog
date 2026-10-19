import { LemonSelect, type LemonSelectOptions } from '@posthog/lemon-ui'

import type {
    AutomaticFlashForEnumApi,
    ReviewRepositoryPersonApi,
    ReviewRepositoryPersonKindEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { PeopleList } from './PeopleList'
import { FLASH_FOR_OPTIONS, peopleKindFor } from './repositoryChoices'
import { RuleStateIcon } from './RuleStateIcon'

const FLASH_FOR_OPTIONS_WITH_ICONS = FLASH_FOR_OPTIONS.map((option) => ({
    ...option,
    icon: <RuleStateIcon flashFor={option.value} />,
}))

/** Who gets automatic reviews, for the project default and for a repository exception alike. */
export function RuleControls({
    label,
    flashFor,
    people,
    canEdit,
    disabledReason,
    onChangeFlashFor,
    onAddPerson,
    onRemovePerson,
    removeException,
    tag,
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
    /** Only for an exception: the picker then offers to remove it, above the rule values. */
    removeException?: { projectFlashFor: AutomaticFlashForEnumApi; onRemove: () => void }
    /** Sits at the right end of the select's line, such as the "Exception" tag of a repository. */
    tag?: React.ReactNode
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
    const options: LemonSelectOptions<AutomaticFlashForEnumApi | 'remove'> = removeException
        ? [
              {
                  options: [
                      {
                          value: 'remove',
                          label: 'Remove exception',
                          icon: <RuleStateIcon flashFor={removeException.projectFlashFor} />,
                          'data-attr': 'review-hog-repository-clear-exception',
                      },
                  ],
              },
              { options: FLASH_FOR_OPTIONS_WITH_ICONS },
          ]
        : FLASH_FOR_OPTIONS_WITH_ICONS
    return (
        // Both people lists sit on their own line under the select, so the select keeps one position in every mode.
        <div className="flex flex-col gap-1.5">
            <span className="flex flex-wrap items-center gap-2">
                <LemonSelect<AutomaticFlashForEnumApi | 'remove'>
                    size="small"
                    aria-label={label}
                    value={flashFor}
                    options={options}
                    onChange={(value) => {
                        if (value === 'remove') {
                            removeException?.onRemove()
                        } else if (value !== flashFor) {
                            onChangeFlashFor(value)
                        }
                    }}
                    disabledReason={disabledReason}
                    data-attr={dataAttr}
                    className="max-w-full self-start"
                />
                {tag && <span className="ml-auto">{tag}</span>}
            </span>
            {peopleList}
        </div>
    )
}
