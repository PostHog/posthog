import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { userLogic } from 'scenes/userLogic'

import type { ScoutOwnerOption } from '../../../utils/scoutOwners'

/**
 * Whose scouts the roster shows: the same people picker as the reports scope control, behind a
 * dropdown button. The options are the fleet's own owners rather than every project member, so the
 * picker can only offer a person some scout matches, and the search runs over that list locally.
 * The count next to each name is how many scouts they own.
 */
export function ScoutOwnerFilter({
    options,
    selected,
    onChange,
    size = 'small',
}: {
    options: ScoutOwnerOption[]
    selected: string | null
    onChange: (owner: string | null) => void
    size?: 'xsmall' | 'small'
}): JSX.Element {
    const { user } = useValues(userLogic)
    const [search, setSearch] = useState('')

    // Your own scouts are the ones you came here to find, so the list says which are yours.
    const nameOf = (option: ScoutOwnerOption): string =>
        option.uuid === user?.uuid ? `${option.name} (you)` : option.name
    const selectedOption = options.find((option) => option.uuid === selected)
    const query = search.trim().toLowerCase()
    const people = options
        .filter(
            (option) =>
                !query || option.name.toLowerCase().includes(query) || option.email.toLowerCase().includes(query)
        )
        .map((option) => ({ uuid: option.uuid, name: nameOf(option), email: option.email, trailing: option.count }))

    return (
        <MemberSelect
            value={selected}
            defaultLabel="Any owner"
            options={people}
            onSearch={setSearch}
            onChange={() => onChange(null)}
            onSelectOption={(uuid) => onChange(uuid)}
        >
            {() => (
                <LemonButton
                    type="secondary"
                    size={size}
                    aria-label="Filter scouts by owner"
                    data-attr="inbox-scout-filter-owner"
                >
                    <span className="max-w-[160px] truncate">
                        {selectedOption ? nameOf(selectedOption) : 'Any owner'}
                    </span>
                </LemonButton>
            )}
        </MemberSelect>
    )
}
