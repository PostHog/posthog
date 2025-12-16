import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonInput, ProfilePicture } from '@posthog/lemon-ui'

import { UserAssignee, userSelectLogic } from './userSelectLogic'

export interface UserDropdownProps {
    userId: number | null
    onChange: (userId: number | null) => void
}

export function UserDropdown({ userId, onChange }: UserDropdownProps): JSX.Element {
    const { search, filteredMembers, membersLoading } = useValues(userSelectLogic)
    const { setSearch } = useActions(userSelectLogic)

    const users: UserAssignee[] = filteredMembers.map((member) => ({
        id: member.user.id,
        user: member.user,
    }))

    return (
        <div className="max-w-100 deprecated-space-y-2 overflow-hidden">
            <LemonInput
                type="search"
                placeholder="Search users"
                autoFocus
                value={search}
                onChange={setSearch}
                fullWidth
            />
            <ul className="deprecated-space-y-px">
                {userId && (
                    <li>
                        <LemonButton
                            fullWidth
                            role="menuitem"
                            size="small"
                            icon={<IconX />}
                            onClick={() => onChange(null)}
                        >
                            Clear filter
                        </LemonButton>
                    </li>
                )}

                {users.map((user) => (
                    <li key={user.id}>
                        <LemonButton
                            fullWidth
                            role="menuitem"
                            size="small"
                            icon={<ProfilePicture user={user.user} size="sm" />}
                            onClick={() => onChange(userId === user.id ? null : user.id)}
                            active={userId === user.id}
                        >
                            <span className="truncate">{user.user.first_name || user.user.email}</span>
                        </LemonButton>
                    </li>
                ))}

                {membersLoading ? (
                    <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                ) : users.length === 0 ? (
                    <div className="p-2 text-secondary italic truncate border-t">
                        <span>No matches</span>
                    </div>
                ) : null}
            </ul>
        </div>
    )
}
