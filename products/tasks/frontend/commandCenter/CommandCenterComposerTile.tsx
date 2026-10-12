import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { SpaceTaskComposer } from '../spaces/SpaceTaskComposer'
import { SpaceTaskComposerSkeleton } from '../spaces/SpaceTaskComposerSkeleton'
import { commandCenterSceneLogic } from './commandCenterSceneLogic'

export interface CommandCenterComposerTileProps {
    index: number
}

export function CommandCenterComposerTile({ index }: CommandCenterComposerTileProps): JSX.Element {
    const { composerSpace, composerRepositoryConfig, spacesLoading, spacesUnavailable } =
        useValues(commandCenterSceneLogic)
    const { placeSession, stopComposing, loadSpaces } = useActions(commandCenterSceneLogic)

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex h-9 shrink-0 items-center gap-1 border-b border-[var(--border)] ps-3 pe-1">
                <span className="min-w-0 flex-1 truncate text-sm font-medium">New chat</span>
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-sm"
                                onClick={() => stopComposing()}
                                aria-label="Cancel"
                                data-attr="command-center-tile-cancel"
                            />
                        }
                    >
                        <IconX />
                    </TooltipTrigger>
                    <TooltipContent>Cancel</TooltipContent>
                </Tooltip>
            </div>
            <div className="flex min-h-0 flex-1 flex-col justify-center overflow-y-auto p-4">
                {composerSpace ? (
                    <SpaceTaskComposer
                        space={composerSpace}
                        panelId={`command-center-${index}`}
                        repositoryConfig={composerRepositoryConfig}
                        onTaskCreated={(sessionId) => placeSession(index, sessionId, 'started')}
                    />
                ) : spacesUnavailable ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>Your spaces didn’t load</EmptyTitle>
                            <EmptyDescription>Check your connection and try again.</EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>
                            <Button
                                variant="outline"
                                loading={spacesLoading}
                                onClick={() => loadSpaces()}
                                data-attr="command-center-tile-retry"
                            >
                                Try again
                            </Button>
                        </EmptyContent>
                    </Empty>
                ) : (
                    <SpaceTaskComposerSkeleton />
                )}
            </div>
        </div>
    )
}
