import { useActions, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { QuillTaskComposerSkeleton } from 'products/posthog_ai/frontend/api/composer'

import { newSessionSceneLogic } from './newSessionSceneLogic'
import { NewSessionSuggestions } from './NewSessionSuggestions'
import { newSessionSuggestionsLogic } from './newSessionSuggestionsLogic'
import { SpaceTaskComposer } from './SpaceTaskComposer'

export const scene: SceneExport = {
    component: NewSessionScene,
    logic: newSessionSceneLogic,
}

export function NewSessionScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { space, spacesLoading, composerRepositoryConfig } = useValues(newSessionSceneLogic)
    const { sessionStarted } = useActions(newSessionSceneLogic)
    const { suggestions, prefillRequest } = useValues(newSessionSuggestionsLogic)
    const { selectSuggestion } = useActions(newSessionSuggestionsLogic)

    if (!enabled) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent className="flex-1">
            {/* Like PostHog Desktop, the middle of the block sits 34% down the pane: the shrink weights take half the block's height from each spacer. */}
            <div className="flex flex-1 flex-col" data-quill>
                <div aria-hidden className="min-h-4 shrink-[66] basis-[34%]" />
                <div className="mx-auto flex w-full max-w-150 shrink-0 flex-col">
                    <h1 className="sr-only">Start a new session</h1>
                    {!space && spacesLoading ? (
                        <QuillTaskComposerSkeleton />
                    ) : (
                        // Each space gets its own composer, so it starts on that space's repository.
                        <div data-attr="today-new-session-composer">
                            <SpaceTaskComposer
                                space={space}
                                panelId={`new-session-${space?.id ?? 'personal'}`}
                                repositoryConfig={composerRepositoryConfig}
                                onTaskCreated={sessionStarted}
                                prefillRequest={prefillRequest}
                            />
                        </div>
                    )}
                </div>
                <div className="mx-auto w-full max-w-150 shrink-[34] basis-[66%]">
                    {suggestions.length > 0 && (
                        <div className="pt-6 pb-4">
                            <NewSessionSuggestions suggestions={suggestions} onSelect={selectSuggestion} />
                        </div>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}
