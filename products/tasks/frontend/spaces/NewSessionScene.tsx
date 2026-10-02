import { useActions, useValues } from 'kea'

import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Skeleton,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'

import { newSessionSceneLogic } from './newSessionSceneLogic'
import { NewSessionSpaceSelect } from './NewSessionSpaceSelect'
import { SPACE_COMPOSER_OVERRIDE } from './spaceSceneLogic'

// The repository picker and the input frame at their loaded sizes, so the page does not jump when the chunk lands.
const COMPOSER_SKELETON = (
    <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-36" />
        <Skeleton className="h-36 w-full rounded-lg" />
    </div>
)

export const scene: SceneExport = {
    component: NewSessionScene,
    logic: newSessionSceneLogic,
}

export function NewSessionScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { space, spaceGroups, sortedSpaces, spacesLoading, spacesUnavailable, composerRepositoryConfig } =
        useValues(newSessionSceneLogic)
    const { pickSpace, sessionStarted, loadSpaces } = useActions(newSessionSceneLogic)

    if (!enabled) {
        return <NotFound object="page" />
    }

    const resolving = !space && spacesLoading
    const failed = !space && spacesUnavailable

    return (
        <SceneContent>
            {/* The same centered column as a space's feed, so the composer does not move between the two pages. */}
            <div className="mx-auto flex w-full max-w-165 flex-col pt-12" data-quill>
                {failed ? (
                    <Empty className="py-12">
                        <EmptyHeader>
                            <EmptyTitle>Your spaces didn’t load</EmptyTitle>
                            <EmptyDescription>Check your connection and try again.</EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>
                            <Button
                                variant="outline"
                                loading={spacesLoading}
                                onClick={() => loadSpaces()}
                                data-attr="today-new-session-retry"
                            >
                                Try again
                            </Button>
                        </EmptyContent>
                    </Empty>
                ) : (
                    <>
                        <Heading size="2xl" render={<h1 />} className="mb-5 flex flex-col">
                            <span>Start a new session</span>
                            <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-muted-foreground">
                                in
                                {resolving ? (
                                    <Skeleton className="h-7 w-28 self-center" />
                                ) : (
                                    <NewSessionSpaceSelect
                                        spaces={sortedSpaces}
                                        groups={spaceGroups}
                                        value={space}
                                        onChange={pickSpace}
                                    />
                                )}
                                <span>space</span>
                            </span>
                        </Heading>
                        {resolving ? (
                            COMPOSER_SKELETON
                        ) : (
                            // Each space gets its own composer, so it starts on that space's repository.
                            <EmbeddedTaskComposer
                                key={space?.id ?? 'none'}
                                panelId={`new-session-${space?.id ?? 'none'}`}
                                channelId={space?.id}
                                initialRepositoryConfig={composerRepositoryConfig}
                                composerOverride={SPACE_COMPOSER_OVERRIDE}
                                onTaskCreated={sessionStarted}
                                fallback={COMPOSER_SKELETON}
                            />
                        )}
                    </>
                )}
            </div>
        </SceneContent>
    )
}
