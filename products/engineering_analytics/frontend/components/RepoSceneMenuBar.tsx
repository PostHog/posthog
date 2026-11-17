import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction, ScenePinned } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { repoScopeLogic } from '../scenes/repoScopeLogic'

const RESOURCE_TYPE = 'engineering-analytics'

interface RepoSceneMenuBarProps {
    repo: string | null
    /** The page's own actions, listed after the rows every repository page shares. */
    sceneActions?: SceneAction[]
    /** Pins the shared "View on GitHub" row, for a page whose title row shows it. */
    viewOnGitHubPinned?: ScenePinned
}

export function RepoSceneMenuBar(props: RepoSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <RepoSceneMenuBarInner {...props} /> : null
}

function RepoSceneMenuBarInner({ repo, sceneActions = [], viewOnGitHubPinned }: RepoSceneMenuBarProps): JSX.Element {
    const { hasMultipleSources, sourceOptions, selectedScope } = useValues(repoScopeLogic)
    const { switchRepo } = useActions(repoScopeLogic)

    const actions: SceneAction[] = [
        ...(repo
            ? ([
                  {
                      group: 'view',
                      section: 'github',
                      id: `${RESOURCE_TYPE}-menubar-view-on-github`,
                      label: 'View on GitHub',
                      icon: <IconExternal />,
                      onSelect: () => window.open(`https://github.com/${repo}`, '_blank', 'noopener,noreferrer'),
                      pinned: viewOnGitHubPinned,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(hasMultipleSources
            ? ([
                  {
                      group: 'view',
                      type: 'radio',
                      id: `${RESOURCE_TYPE}-menubar-switch-repo`,
                      label: 'Switch repository',
                      value: selectedScope ?? '',
                      options: sourceOptions.map((option) => ({ value: option.value, label: option.label })),
                      onValueChange: (value) => {
                          if (value !== selectedScope) {
                              switchRepo(value)
                          }
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...sceneActions,
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
