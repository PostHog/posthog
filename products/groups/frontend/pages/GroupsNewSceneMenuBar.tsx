import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCheck, IconX } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { groupsNewLogic } from 'products/groups/frontend/logics/groupsNewLogic'

const RESOURCE_TYPE = 'group-new'

export function GroupsNewSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <GroupsNewSceneMenuBarInner /> : null
}

function GroupsNewSceneMenuBarInner(): JSX.Element {
    const { logicProps, isGroupSubmitting } = useValues(groupsNewLogic)
    const { submitGroup } = useActions(groupsNewLogic)

    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-cancel`,
            label: 'Cancel',
            icon: <IconX />,
            onSelect: () => router.actions.push(urls.groups(logicProps.groupTypeIndex)),
            pinned: { order: 1, variant: 'secondary', dataAttr: 'cancel-group' },
        },
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save`,
            label: 'Save',
            icon: <IconCheck />,
            disabledReason: isGroupSubmitting ? 'Saving the group' : undefined,
            onSelect: submitGroup,
            pinned: { order: 1, variant: 'primary', dataAttr: 'save-group' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
