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
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { SpaceFeed } from './SpaceFeed'
import { SpaceSceneLogicProps, SpaceTab, spaceSceneLogic } from './spaceSceneLogic'
import { SpaceSettings } from './SpaceSettings'

export const scene: SceneExport<SpaceSceneLogicProps> = {
    component: SpaceScene,
    logic: spaceSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function SpaceScene({ id }: SpaceSceneLogicProps): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { space, spaceLoading, spaceUnavailable, spaceMissing, activeTab, savingSpace } = useValues(
        spaceSceneLogic({ id })
    )
    const { setStarred, loadSpace } = useActions(spaceSceneLogic({ id }))

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
                <Tabs
                    value={activeTab}
                    onValueChange={(tab: SpaceTab) =>
                        router.actions.push(tab === 'settings' ? urls.taskSpaceSettings(id) : urls.taskSpace(id))
                    }
                    data-quill
                >
                    <TabsList variant="line">
                        <TabsTrigger value="feed" data-attr="today-space-tab-feed">
                            Feed
                        </TabsTrigger>
                        <TabsTrigger value="settings" data-attr="today-space-tab-settings">
                            Settings
                        </TabsTrigger>
                    </TabsList>
                    <TabsContent value="feed">
                        <SpaceFeed id={id} />
                    </TabsContent>
                    <TabsContent value="settings" data-not-quill>
                        <SpaceSettings key={space?.id} id={id} />
                    </TabsContent>
                </Tabs>
            </SceneContent>
        </TooltipProvider>
    )
}
