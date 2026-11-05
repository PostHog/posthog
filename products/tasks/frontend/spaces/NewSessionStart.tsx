import { useActions, useValues } from 'kea'

import { QuillTaskComposerSkeleton } from 'products/posthog_ai/frontend/api/composer'

import { NewSessionSurface, newSessionSceneLogic } from './newSessionSceneLogic'
import { NewSessionSuggestions } from './NewSessionSuggestions'
import { newSessionSuggestionsLogic } from './newSessionSuggestionsLogic'
import { SpaceTaskComposer } from './SpaceTaskComposer'

// pinned: data-attr values. Autocapture dashboards and Playwright select them.
const COMPOSER_DATA_ATTR: Record<NewSessionSurface, string> = {
    new_session: 'today-new-session-composer',
    home_ask: 'today-home-ask-composer',
}

export interface NewSessionStartProps {
    heading: string
    surface: NewSessionSurface
}

/** The heading, composer and suggestions that start a new session, on the New session page and the Today home Ask tab. */
export function NewSessionStart({ heading, surface }: NewSessionStartProps): JSX.Element {
    const { space, spacesLoading, composerRepositoryConfig } = useValues(newSessionSceneLogic)
    const { sessionStarted } = useActions(newSessionSceneLogic)
    const { suggestions, prefillRequest } = useValues(newSessionSuggestionsLogic)
    const { selectSuggestion } = useActions(newSessionSuggestionsLogic)

    return (
        // Like PostHog Desktop, the middle of the block sits 34% down the pane: the shrink weights take half the block's height from each spacer.
        <div className="flex flex-1 flex-col" data-quill>
            <div aria-hidden className="min-h-4 shrink-[66] basis-[34%]" />
            <div className="mx-auto flex w-full max-w-150 shrink-0 flex-col">
                <h1 className="mb-6 text-center text-2xl font-semibold">{heading}</h1>
                {!space && spacesLoading ? (
                    <QuillTaskComposerSkeleton />
                ) : (
                    // Each space gets its own composer, so it starts on that space's repository.
                    <div data-attr={COMPOSER_DATA_ATTR[surface]}>
                        <SpaceTaskComposer
                            space={space}
                            panelId={`new-session-${space?.id ?? 'personal'}`}
                            repositoryConfig={composerRepositoryConfig}
                            onTaskCreated={(sessionId) => sessionStarted(sessionId, surface)}
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
    )
}
