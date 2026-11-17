import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { newSpaceLogic } from './newSpaceLogic'

const RESOURCE_TYPE = 'spaces'

export function SpacesSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <SpacesSceneMenuBarInner /> : null
}

function SpacesSceneMenuBarInner(): JSX.Element {
    const { openNewSpace } = useActions(newSpaceLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-space`,
            label: 'New space',
            icon: <IconPlus />,
            opensFloatingUi: true,
            onSelect: openNewSpace,
            pinned: { order: 1, variant: 'primary', dataAttr: 'today-new-space-open-index' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
