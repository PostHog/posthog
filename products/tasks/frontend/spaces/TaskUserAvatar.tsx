import { Avatar, AvatarFallback, AvatarImage } from '@posthog/quill'

import { NUM_LETTERMARK_STYLES } from 'lib/lemon-ui/Lettermark/Lettermark'
import { inStorybookTestRunner } from 'lib/utils/dom'
import { gravatarUrl } from 'lib/utils/gravatar'

import { TaskUserBasicInfoApi } from '../generated/api.schemas'

export type TaskAvatarUser = Pick<TaskUserBasicInfoApi, 'first_name' | 'last_name' | 'email'> & {
    uuid?: string | null
}

export function taskUserName(user: TaskAvatarUser): string {
    return [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email
}

function initials(name: string): string {
    return name
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase())
        .join('')
}

/** PostHog Desktop's seed hash, so a person keeps the same color in both apps. */
export function avatarColorIndex(seed: string): number {
    let hash = 0
    for (let index = 0; index < seed.length; index += 1) {
        hash = (hash + seed.charCodeAt(index) * (index + 1)) % 9973
    }
    return (hash % NUM_LETTERMARK_STYLES) + 1
}

/** A person's Gravatar, or their initials on their own lettermark color. */
export function TaskUserAvatar({ user, className }: { user: TaskAvatarUser; className?: string }): JSX.Element {
    const name = taskUserName(user)
    const color = avatarColorIndex(user.uuid || user.email || name)
    return (
        <Avatar size="xs" className={className}>
            {/* A Gravatar loads at an unknown time, so snapshots keep the initials. */}
            {user.email && !inStorybookTestRunner() && <AvatarImage src={gravatarUrl(user.email)} alt={name} />}
            <AvatarFallback
                // The palette is 16 theme-independent pairs in base.scss, picked per person at runtime.
                style={{
                    backgroundColor: `var(--lettermark-${color}-bg)`,
                    color: `var(--lettermark-${color}-text)`,
                }}
            >
                {initials(name)}
            </AvatarFallback>
        </Avatar>
    )
}
