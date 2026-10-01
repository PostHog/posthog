import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconStar, IconStarFilled } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'

import { SpaceFeed } from './SpaceFeed'
import { SpaceSceneLogicProps, SpaceTab, spaceSceneLogic } from './spaceSceneLogic'
import { SpaceSettings } from './SpaceSettings'

const SPACE_COMPOSER_OVERRIDE = {
    placeholder: 'What do you want to ship?',
    hideSuggestions: true,
    hideRecentTasks: true,
    hideOnboardingReplay: true,
}

// The repository picker and the input frame at their loaded sizes, so the feed does not jump when the chunk lands.
const COMPOSER_SKELETON = (
    <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-36" />
        <Skeleton className="h-36 w-full rounded-lg" />
    </div>
)

export const scene: SceneExport<SpaceSceneLogicProps> = {
    component: SpaceScene,
    logic: spaceSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function SpaceScene({ id }: SpaceSceneLogicProps): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const {
        space,
        spaceLoading,
        spaceUnavailable,
        spaceMissing,
        activeTab,
        savingSpace,
        composerRepositoryConfig,
        composerFocusRequest,
    } = useValues(spaceSceneLogic({ id }))
    const { setStarred, loadSpace, sessionStarted } = useActions(spaceSceneLogic({ id }))

    if (!enabled || spaceMissing) {
        return <NotFound object="space" />
    }
    if (spaceUnavailable && !space) {
        return (
            <SceneContent>
                <Empty className="py-12" data-quill>
                    <EmptyHeader>
                        <EmptyTitle>This space didn’t load</EmptyTitle>
                        <EmptyDescription>Check your connection and try again.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={spaceLoading}
                            onClick={() => loadSpace()}
                            data-attr="today-space-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            </SceneContent>
        )
    }
    const starLabel = space?.starred ? 'Unstar space' : 'Star space'
    return (
        <TooltipProvider>
            <SceneContent>
                <SceneTitleSection
                    name={space ? spaceLabel(space) : null}
                    isLoading={spaceLoading && !space}
                    resourceType={{ type: 'task' }}
                    nameSuffix={
                        space && space.system_role !== 'personal' ? (
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={
                                        <Button
                                            size="icon-sm"
                                            aria-label={starLabel}
                                            aria-pressed={space.starred}
                                            disabled={savingSpace}
                                            onClick={() => setStarred(!space.starred)}
                                            data-attr="today-space-star"
                                        />
                                    }
                                >
                                    {space.starred ? (
                                        <IconStarFilled className="text-warning-foreground" />
                                    ) : (
                                        <IconStar />
                                    )}
                                </TooltipTrigger>
                                <TooltipContent>{savingSpace ? 'Saving your last change' : starLabel}</TooltipContent>
                            </Tooltip>
                        ) : null
                    }
                />
                {/* Pulled up to the title and ruled off full width, like PostHog Desktop's space tabs. */}
                <Tabs
                    value={activeTab}
                    onValueChange={(tab: SpaceTab) =>
                        router.actions.push(tab === 'settings' ? urls.taskSpaceSettings(id) : urls.taskSpace(id))
                    }
                    className="-mt-4"
                    data-quill
                >
                    <div className="-mx-4 border-b border-border px-4">
                        <TabsList variant="line" aria-label="Space pages">
                            <TabsTrigger value="feed" data-attr="today-space-tab-feed">
                                Feed
                            </TabsTrigger>
                            <TabsTrigger value="settings" data-attr="today-space-tab-settings">
                                Settings
                            </TabsTrigger>
                        </TabsList>
                    </div>
                    <TabsContent value="feed">
                        {/* The same centered column and top inset as PostHog Desktop's space feed. */}
                        <div className="mx-auto flex w-full max-w-165 flex-col pt-3">
                            {/* Mounted once the space loads, so the composer starts on the space's repository. */}
                            {space && (
                                <div className="mb-1 border-b border-border pb-4" data-attr="today-space-new-task">
                                    <EmbeddedTaskComposer
                                        key={space.id}
                                        panelId={`space-${space.id}`}
                                        channelId={space.id}
                                        initialRepositoryConfig={composerRepositoryConfig}
                                        composerOverride={SPACE_COMPOSER_OVERRIDE}
                                        onTaskCreated={sessionStarted}
                                        focusRequest={composerFocusRequest}
                                        autoFocus={false}
                                        fallback={COMPOSER_SKELETON}
                                    />
                                </div>
                            )}
                            <SpaceFeed id={id} />
                        </div>
                    </TabsContent>
                    <TabsContent value="settings">
                        <SpaceSettings key={space?.id} id={id} />
                    </TabsContent>
                </Tabs>
            </SceneContent>
        </TooltipProvider>
    )
}
