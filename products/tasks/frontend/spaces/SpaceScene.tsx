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
import { useResolvedFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { SpaceCanvases } from './SpaceCanvases'
import { SpaceFeed } from './SpaceFeed'
import { SpaceSceneLogicProps, SpaceTab, spaceComposerPanelId, spaceSceneLogic } from './spaceSceneLogic'
import { SpaceSettings } from './SpaceSettings'
import { SpaceTaskComposer } from './SpaceTaskComposer'

export const scene: SceneExport<SpaceSceneLogicProps> = {
    component: SpaceScene,
    logic: spaceSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function SpaceScene({ id }: SpaceSceneLogicProps): JSX.Element {
    const enabled = useResolvedFeatureFlag('TODAY_RAIL_NAV')
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

    if (enabled === null) {
        return (
            <SceneContent>
                <SceneTitleSection name={null} isLoading resourceType={{ type: 'task' }} />
            </SceneContent>
        )
    }
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
                        router.actions.push(
                            tab === 'settings'
                                ? urls.taskSpaceSettings(id)
                                : tab === 'canvases'
                                  ? urls.taskSpaceCanvases(id)
                                  : urls.taskSpace(id)
                        )
                    }
                    className="-mt-4"
                    data-quill
                >
                    <div className="-mx-4 border-b border-border px-4">
                        <TabsList variant="line" aria-label="Space pages">
                            <TabsTrigger value="feed" data-attr="today-space-tab-feed">
                                Activity
                            </TabsTrigger>
                            <TabsTrigger value="canvases" data-attr="today-space-tab-canvases">
                                Canvases
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
                                    <SpaceTaskComposer
                                        space={space}
                                        panelId={spaceComposerPanelId(id)}
                                        repositoryConfig={composerRepositoryConfig}
                                        onTaskCreated={sessionStarted}
                                        focusRequest={composerFocusRequest}
                                    />
                                </div>
                            )}
                            <SpaceFeed id={id} />
                        </div>
                    </TabsContent>
                    <TabsContent value="canvases">
                        <SpaceCanvases id={id} />
                    </TabsContent>
                    <TabsContent value="settings">
                        <SpaceSettings key={space?.id} id={id} />
                    </TabsContent>
                </Tabs>
            </SceneContent>
        </TooltipProvider>
    )
}
