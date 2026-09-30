import { useActions, useValues } from 'kea'

import { IconLock, IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { ChannelDTOApi } from '../generated/api.schemas'
import { spacesSceneLogic } from './spacesSceneLogic'

export function SpacesIndexRow({ space }: { space: ChannelDTOApi }): JSX.Element {
    const { pendingSpaceIds } = useValues(spacesSceneLogic)
    const { toggleStar } = useActions(spacesSceneLogic)
    const personal = space.system_role === 'personal'

    return (
        <div className="flex items-center gap-1 rounded hover:bg-fill-button-tertiary-hover">
            <Link
                to={urls.taskSpace(space.id)}
                subtle
                className="flex h-9 min-w-0 flex-1 items-center gap-3 px-2"
                data-attr="today-spaces-index-row"
            >
                <span className="flex w-4 shrink-0 justify-center text-secondary" aria-hidden>
                    {space.channel_type === 'private' ? <IconLock /> : '#'}
                </span>
                <span className="shrink-0 truncate font-medium">{spaceLabel(space)}</span>
                <span className="min-w-0 flex-1 truncate text-xs text-secondary">{space.repositories.join(', ')}</span>
            </Link>
            {!personal && (
                <LemonButton
                    size="small"
                    icon={space.starred ? <IconStarFilled className="text-warning" /> : <IconStar />}
                    tooltip={space.starred ? 'Unstar space' : 'Star space'}
                    disabledReason={pendingSpaceIds.includes(space.id) ? 'Saving your last change' : undefined}
                    onClick={() => toggleStar(space.id, !space.starred)}
                    data-attr="today-spaces-index-star"
                />
            )}
        </div>
    )
}
