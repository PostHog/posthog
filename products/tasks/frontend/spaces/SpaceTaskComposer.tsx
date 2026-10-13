import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'

import { ChannelDTOApi } from '../generated/api.schemas'
import { SpaceComposerRepositoryConfig } from './spaceSceneLogic'
import { SpaceTaskComposerSkeleton } from './SpaceTaskComposerSkeleton'

const SPACE_COMPOSER_OVERRIDE = {
    placeholder: 'What do you want to ship?',
    hideSuggestions: true,
    hideRecentTasks: true,
    hideOnboardingReplay: true,
}

export interface SpaceTaskComposerProps {
    space: ChannelDTOApi
    panelId: string
    repositoryConfig: SpaceComposerRepositoryConfig
    onTaskCreated: (sessionId: string) => void
    focusRequest?: number
}

/** The new-session composer that files into a space, on the space's activity tab and on the new session page. */
export function SpaceTaskComposer({
    space,
    panelId,
    repositoryConfig,
    onTaskCreated,
    focusRequest,
}: SpaceTaskComposerProps): JSX.Element {
    return (
        <EmbeddedTaskComposer
            key={space.id}
            panelId={panelId}
            channelId={space.id}
            initialRepositoryConfig={repositoryConfig}
            composerOverride={SPACE_COMPOSER_OVERRIDE}
            onTaskCreated={onTaskCreated}
            focusRequest={focusRequest}
            autoFocus={false}
            fallback={<SpaceTaskComposerSkeleton />}
        />
    )
}
