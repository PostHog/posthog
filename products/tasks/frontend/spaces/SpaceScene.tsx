import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

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
                <div className="TodayPane__state">
                    <span>This space didn’t load.</span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        loading={spaceLoading}
                        onClick={() => loadSpace()}
                        data-attr="today-space-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }
    return (
        <SceneContent>
            <SceneTitleSection
                name={space ? spaceLabel(space) : null}
                isLoading={spaceLoading && !space}
                resourceType={{ type: 'task' }}
                nameSuffix={
                    space && space.system_role !== 'personal' ? (
                        <LemonButton
                            size="small"
                            icon={space.starred ? <IconStarFilled className="text-warning" /> : <IconStar />}
                            tooltip={space.starred ? 'Unstar space' : 'Star space'}
                            disabledReason={savingSpace ? 'Saving your last change' : undefined}
                            onClick={() => setStarred(!space.starred)}
                            data-attr="today-space-star"
                        />
                    ) : null
                }
            />
            <LemonTabs<SpaceTab>
                activeKey={activeTab}
                onChange={(tab) =>
                    router.actions.push(tab === 'settings' ? urls.taskSpaceSettings(id) : urls.taskSpace(id))
                }
                tabs={[
                    { key: 'feed', label: 'Feed', content: <SpaceFeed id={id} /> },
                    { key: 'settings', label: 'Settings', content: <SpaceSettings key={space?.id} id={id} /> },
                ]}
            />
        </SceneContent>
    )
}
