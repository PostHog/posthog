import { useActions, useValues } from 'kea'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { newSessionSceneLogic } from './newSessionSceneLogic'
import { NewSessionSuggestions } from './NewSessionSuggestions'
import { newSessionSuggestionsLogic } from './newSessionSuggestionsLogic'
import { SpaceTaskComposer } from './SpaceTaskComposer'
import { SpaceTaskComposerSkeleton } from './SpaceTaskComposerSkeleton'

export const scene: SceneExport = {
    component: NewSessionScene,
    logic: newSessionSceneLogic,
}

export function NewSessionScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { space, spacesLoading, spacesUnavailable, composerRepositoryConfig } = useValues(newSessionSceneLogic)
    const { sessionStarted, loadSpaces } = useActions(newSessionSceneLogic)
    const { suggestions, prefillRequest } = useValues(newSessionSuggestionsLogic)
    const { selectSuggestion } = useActions(newSessionSuggestionsLogic)

    if (!enabled) {
        return <NotFound object="page" />
    }

    const resolving = !space && spacesLoading
    const failed = !space && spacesUnavailable

    return (
        <SceneContent className="flex-1">
            {/* Like PostHog Desktop, the middle of the block sits 34% down the pane: the shrink weights take half the block's height from each spacer. */}
            <div className="flex flex-1 flex-col" data-quill>
                <div aria-hidden className="min-h-4 shrink-[66] basis-[34%]" />
                <div className="mx-auto flex w-full max-w-150 shrink-0 flex-col">
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
                            <h1 className="sr-only">Start a new session</h1>
                            {resolving ? (
                                <SpaceTaskComposerSkeleton />
                            ) : (
                                space && (
                                    // Each space gets its own composer, so it starts on that space's repository.
                                    <div data-attr="today-new-session-composer">
                                        <SpaceTaskComposer
                                            space={space}
                                            panelId={`new-session-${space.id}`}
                                            repositoryConfig={composerRepositoryConfig}
                                            onTaskCreated={sessionStarted}
                                            prefillRequest={prefillRequest}
                                        />
                                    </div>
                                )
                            )}
                        </>
                    )}
                </div>
                <div className="mx-auto w-full max-w-150 shrink-[34] basis-[66%]">
                    {space && suggestions.length > 0 && (
                        <div className="pt-6 pb-4">
                            <NewSessionSuggestions suggestions={suggestions} onSelect={selectSuggestion} />
                        </div>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}
