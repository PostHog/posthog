import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction, ScenePinned } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import type { RepoApi } from '../generated/api.schemas'
import { splitRepoFullName } from '../lib/repoPaths'
import { visualReviewRepoLogic } from '../scenes/visualReviewRepoLogic'
import type { VisualReviewTabKey } from './VisualReviewTabs'

const RESOURCE_TYPE = 'visual-review'

const TAB_TO_PATH: Record<VisualReviewTabKey, (repoFullName: string) => string> = {
    runs: (repoFullName) => urls.visualReviewRepoRuns(...splitRepoFullName(repoFullName)),
    snapshots: (repoFullName) => urls.visualReviewSnapshotOverview(...splitRepoFullName(repoFullName)),
    flakiness: (repoFullName) => urls.visualReviewFlakiness(...splitRepoFullName(repoFullName)),
}

interface VisualReviewSceneMenuBarProps {
    repoFullName: string
    activeTab: VisualReviewTabKey
    /** The page's own actions, listed after the rows every repository page shares. */
    sceneActions?: SceneAction[]
    /** Pins the shared Settings row, for a page whose title row shows it. */
    settingsPinned?: ScenePinned
}

export function VisualReviewSceneMenuBar(props: VisualReviewSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <VisualReviewSceneMenuBarInner {...props} /> : null
}

function VisualReviewSceneMenuBarInner({
    repoFullName,
    activeTab,
    sceneActions = [],
    settingsPinned,
}: VisualReviewSceneMenuBarProps): JSX.Element {
    const { otherRepos } = useValues(visualReviewRepoLogic({ repoFullName }))

    const actions: SceneAction[] = [
        {
            group: 'view',
            section: 'settings',
            id: `${RESOURCE_TYPE}-menubar-settings`,
            label: 'Settings',
            icon: <IconGear />,
            onSelect: () => router.actions.push(urls.visualReviewSettings()),
            pinned: settingsPinned,
        },
        ...(otherRepos.length > 0
            ? ([
                  {
                      group: 'view',
                      section: 'repos',
                      type: 'submenu',
                      id: 'visual-review-repo-switcher',
                      label: 'Switch repository',
                      items: otherRepos.map((repo: RepoApi) => ({
                          id: `${RESOURCE_TYPE}-menubar-switch-repo-${repo.id}`,
                          dataAttr: `${RESOURCE_TYPE}-menubar-switch-repo`,
                          label: repo.repo_full_name,
                          onSelect: () => router.actions.push(TAB_TO_PATH[activeTab](repo.repo_full_name)),
                      })),
                  },
              ] satisfies SceneAction[])
            : []),
        ...sceneActions,
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
