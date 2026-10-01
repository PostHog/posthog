import { useActions, useValues } from 'kea'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodaySpaceGlyph } from '~/layout/today/TodaySpaceGlyph'
import { isLockedSpace, spaceLabel } from '~/layout/today/todaySpacesLogic'

import { ChannelDTOApi } from '../generated/api.schemas'
import { spacesSceneLogic } from './spacesSceneLogic'

export function SpacesIndexRow({ space }: { space: ChannelDTOApi }): JSX.Element {
    const { pendingSpaceIds } = useValues(spacesSceneLogic)
    const { toggleStar } = useActions(spacesSceneLogic)
    const personal = space.system_role === 'personal'
    const starLabel = space.starred ? 'Unstar space' : 'Star space'
    const saving = pendingSpaceIds.includes(space.id)

    return (
        <div className="relative flex min-w-0 items-center">
            <Button
                size="row"
                left
                render={<LinkPrimitive to={urls.taskSpace(space.id)} />}
                className="h-9 min-w-0 flex-1 gap-3 pr-10"
                data-attr="today-spaces-index-row"
            >
                <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground" aria-hidden>
                    <TodaySpaceGlyph locked={isLockedSpace(space)} />
                </span>
                <span className="shrink-0 truncate font-medium">{spaceLabel(space)}</span>
                <Text render={<span />} size="xs" variant="muted" className="min-w-0 flex-1 truncate">
                    {space.repositories.join(', ')}
                </Text>
            </Button>
            {!personal && (
                <div className="absolute right-1 flex">
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Button
                                    size="icon-sm"
                                    aria-label={starLabel}
                                    aria-pressed={space.starred}
                                    disabled={saving}
                                    onClick={() => toggleStar(space.id, !space.starred)}
                                    data-attr="today-spaces-index-star"
                                />
                            }
                        >
                            {space.starred ? <IconStarFilled className="text-warning-foreground" /> : <IconStar />}
                        </TooltipTrigger>
                        <TooltipContent>{saving ? 'Saving your last change' : starLabel}</TooltipContent>
                    </Tooltip>
                </div>
            )}
        </div>
    )
}
