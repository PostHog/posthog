import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { QuillAddRepoDropdown } from './QuillAddRepoDropdown'

const RESOURCE_TYPE = 'visual-review-settings'

interface VisualReviewSettingsSceneMenuBarProps {
    hasGitHub: boolean
}

export function VisualReviewSettingsSceneMenuBar(props: VisualReviewSettingsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <VisualReviewSettingsSceneMenuBarInner {...props} /> : null
}

function VisualReviewSettingsSceneMenuBarInner({ hasGitHub }: VisualReviewSettingsSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = hasGitHub
        ? [
              {
                  group: 'file',
                  section: 'create',
                  type: 'panel',
                  id: `${RESOURCE_TYPE}-menubar-add-repo`,
                  label: 'Add a repository',
                  icon: <IconPlus />,
                  render: () => <QuillAddRepoDropdown />,
                  pinned: { order: 1, variant: 'primary', render: () => <QuillAddRepoDropdown /> },
              },
          ]
        : []

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
