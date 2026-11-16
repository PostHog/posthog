import { Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullName } from 'lib/utils/strings'

import type { ReleaseAllOwner as Owner } from './releaseAllLogic'

export function ReleaseAllOwner({ owner }: { owner: Owner | null }): JSX.Element {
    if (!owner) {
        return (
            <Text size="xs" variant="muted">
                –
            </Text>
        )
    }
    const full = fullName(owner)
    const label = owner.first_name?.trim() || owner.email.split('@')[0]
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="flex min-w-0 items-center gap-1.5" />}>
                <QuillPersonAvatar name={label} email={owner.email} size="xs" />
                <Text size="xs" className="truncate">
                    {label}
                </Text>
            </TooltipTrigger>
            <TooltipContent>{full && full !== 'Unknown User' ? full : owner.email}</TooltipContent>
        </Tooltip>
    )
}
