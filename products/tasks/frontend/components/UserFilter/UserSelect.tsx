import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonDropdown, ProfilePicture } from '@posthog/lemon-ui'

import { UserDropdown } from './UserDropdown'
import { UserAssignee, userSelectLogic } from './userSelectLogic'

export const UserSelect = ({
    userId,
    onChange,
    children,
}: {
    userId: number | null
    onChange: (userId: number | null) => void
    children: (user: UserAssignee | null, isOpen: boolean) => JSX.Element
}): JSX.Element => {
    const { setSearch, ensureUsersLoaded } = useActions(userSelectLogic)
    const { users } = useValues(userSelectLogic)
    const [showPopover, setShowPopover] = useState(false)

    const _onChange = (value: number | null): void => {
        setSearch('')
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        ensureUsersLoaded()
    }, [ensureUsersLoaded])

    const selectedUser = userId ? (users.find((u) => u.id === userId) ?? null) : null

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={<UserDropdown userId={userId} onChange={_onChange} />}
        >
            <div>{children(selectedUser, showPopover)}</div>
        </LemonDropdown>
    )
}

export const UserDisplay = ({ user }: { user: UserAssignee | null }): JSX.Element => {
    if (!user) {
        return <span className="text-muted">Any user</span>
    }

    return (
        <div className="flex items-center gap-2">
            <ProfilePicture user={user.user} size="sm" />
            <span className="truncate">{user.user.first_name || user.user.email}</span>
        </div>
    )
}
