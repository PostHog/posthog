import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import type { ScoutOwnerOption } from '../../../utils/scoutOwners'
import { InboxPeoplePicker } from '../../shell/InboxPeoplePicker'

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
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const [referenceEl, setReferenceEl] = useState<HTMLDivElement | null>(null)

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

    const pick = (owner: string | null): void => {
        onChange(owner)
        setOpen(false)
        setSearch('')
    }

    return (
        <>
            <div ref={setReferenceEl} className="inline-flex">
                <LemonButton
                    type="secondary"
                    size={size}
                    active={open}
                    onClick={() => setOpen((value) => !value)}
                    aria-label="Filter scouts by owner"
                    data-attr="inbox-scout-filter-owner"
                    sideIcon={<IconChevronDown />}
                >
                    <span className="max-w-[160px] truncate">
                        {selectedOption ? nameOf(selectedOption) : 'Any owner'}
                    </span>
                </LemonButton>
            </div>
            <InboxPeoplePicker
                visible={open}
                referenceElement={referenceEl}
                onClose={() => setOpen(false)}
                search={search}
                onSearch={setSearch}
                people={people}
                selectedUuid={selected}
                everyoneLabel="Any owner"
                onPick={(person) => pick(person?.uuid ?? null)}
            />
        </>
    )
}
