import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSnack } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { fullNameOrEmail } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import type {
    ReviewRepositoryPersonApi,
    ReviewRepositoryPersonKindEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

export function PeopleList({
    kind,
    people,
    canEdit,
    disabledReason,
    onAdd,
    onRemove,
}: {
    kind: ReviewRepositoryPersonKindEnumApi
    people: readonly ReviewRepositoryPersonApi[]
    canEdit: boolean
    disabledReason?: string
    onAdd: (userId: number) => void
    onRemove: (person: ReviewRepositoryPersonApi) => void
}): JSX.Element {
    const { user } = useValues(userLogic)
    const listed = people.filter((person) => person.kind === kind)

    return (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-secondary">{kind === 'excepted' ? 'except:' : 'People:'}</span>
            {listed.map((person) => (
                <LemonSnack
                    key={person.id}
                    title={person.user.email}
                    onClose={canEdit && !disabledReason ? () => onRemove(person) : undefined}
                    data-attr="review-hog-rule-person"
                >
                    {fullNameOrEmail(person.user)}
                    {person.user.id === user?.id ? ' (you)' : ''}
                </LemonSnack>
            ))}
            {listed.length === 0 && <span className="text-tertiary">nobody yet</span>}
            {canEdit && (
                <MemberSelect
                    value={null}
                    allowNone={false}
                    excludedMembers={listed.map((person) => person.user.id)}
                    onChange={(member) => member && onAdd(member.id)}
                >
                    {() => (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconPlus />}
                            disabledReason={disabledReason}
                            data-attr="review-hog-rule-add-person"
                        >
                            Person
                        </LemonButton>
                    )}
                </MemberSelect>
            )}
        </div>
    )
}
