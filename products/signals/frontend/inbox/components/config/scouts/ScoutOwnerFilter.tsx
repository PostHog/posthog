import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import type { ScoutOwnerOption } from '../../../utils/scoutOwners'

/**
 * Whose scouts the roster shows. Single-select, and the options are the fleet's own owners rather
 * than every project member, so the control can only offer a person some scout matches. The count
 * next to each name is how many scouts they own.
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

    return (
        <LemonSelect
            size={size}
            value={selected}
            onChange={onChange}
            aria-label="Filter scouts by owner"
            data-attr="inbox-scout-filter-owner"
            options={[
                { value: null, label: 'Any owner' },
                ...options.map((option) => {
                    // Your own scouts are the ones you came here to find, so the list says which are yours.
                    const label = option.uuid === user?.uuid ? `${option.name} (you)` : option.name
                    return {
                        value: option.uuid,
                        label,
                        // Two teammates can share a display name, and the fallback name is already the email.
                        tooltip: option.name === option.email ? undefined : option.email,
                        labelInMenu: (
                            <span className="flex min-w-40 items-center justify-between gap-3">
                                <span className="truncate">{label}</span>
                                <span className="text-muted tabular-nums">{option.count}</span>
                            </span>
                        ),
                    }
                }),
            ]}
        />
    )
}
