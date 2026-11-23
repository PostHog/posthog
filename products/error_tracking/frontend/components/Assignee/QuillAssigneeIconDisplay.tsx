import { match } from 'ts-pattern'

import { IconPerson } from '@posthog/icons'
import { Avatar, AvatarFallback } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullName } from 'lib/utils/strings'

import { AssigneeIconDisplayProps } from './AssigneeDisplay'

function quillAvatarSize(size: AssigneeIconDisplayProps['size']): 'xs' | 'sm' | 'default' {
    if (size === 'xsmall') {
        return 'xs'
    }
    if (size === 'small') {
        return 'sm'
    }
    return 'default'
}

export function QuillAssigneeIconDisplay({ assignee, size }: AssigneeIconDisplayProps): JSX.Element {
    const avatarSize = quillAvatarSize(size)

    return match(assignee)
        .with({ type: 'role' }, ({ role }) => <QuillPersonAvatar name={role.name} size={avatarSize} />)
        .with({ type: 'user' }, ({ user }) => (
            <QuillPersonAvatar name={fullName(user)} email={user.email} size={avatarSize} />
        ))
        .otherwise(() => (
            <Avatar size={avatarSize}>
                <AvatarFallback className="border border-dashed border-border bg-transparent text-muted-foreground">
                    <IconPerson />
                </AvatarFallback>
            </Avatar>
        ))
}
