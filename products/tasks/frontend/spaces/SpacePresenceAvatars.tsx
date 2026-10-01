import { IconCrown } from '@posthog/icons'
import { AvatarGroup, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SpacePresence } from './spacePresence'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'

function personLabel(name: string, creator: boolean, live: boolean): string {
    if (creator) {
        return live ? `${name} created this space and is working here now` : `${name} created this space`
    }
    return live ? `${name} is working here now` : name
}

/**
 * Who has been active in a space lately, like PostHog Desktop. A small corner dot marks who is working right now,
 * and a crown marks the creator when `creatorUuid` is given.
 * The newest person sits on top at the right, so their dot shows; the stack tucks the others behind them.
 */
export function SpacePresenceAvatars({
    presence,
    creatorUuid = null,
}: {
    presence: SpacePresence
    creatorUuid?: string | null
}): JSX.Element | null {
    if (!presence.people.length) {
        return null
    }
    return (
        <AvatarGroup stacked reverse size="xs" data-attr="today-space-presence">
            {[...presence.people].reverse().map((person) => {
                const live = presence.liveUuids.includes(person.uuid)
                const creator = person.uuid === creatorUuid
                const label = personLabel(taskUserName(person), creator, live)
                return (
                    <Tooltip key={person.uuid}>
                        <TooltipTrigger
                            render={<span role="img" aria-label={label} className="relative flex shrink-0" />}
                        >
                            <TaskUserAvatar user={person} />
                            {creator && (
                                // Top left: the stack covers each face's right side, and the live dot takes the bottom right.
                                <span className="absolute -top-1 -left-1 flex rounded-full bg-card p-px">
                                    <IconCrown className="size-2 text-foreground" />
                                </span>
                            )}
                            {live && (
                                // Desktop's corner dot. The background ring lifts it off the face, and it never grows over it.
                                <span className="absolute right-0 bottom-0 size-1.5 rounded-full bg-primary ring-1 ring-background" />
                            )}
                        </TooltipTrigger>
                        <TooltipContent>{label}</TooltipContent>
                    </Tooltip>
                )
            })}
        </AvatarGroup>
    )
}
