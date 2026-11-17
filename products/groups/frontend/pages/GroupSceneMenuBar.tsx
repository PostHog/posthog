import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { useAddToNotebookAction } from 'scenes/notebooks/useAddToNotebookAction'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { useTodayPeoplePinAction } from '~/layout/today/useTodayPeoplePinAction'

import { feedbackSceneAction } from 'products/customer_analytics/frontend/components/feedbackSceneAction'

const RESOURCE_TYPE = 'group'
// pinned: the feedback survey targets this element id
const FEEDBACK_BUTTON_ID = 'customer-analytics-group-profile-feedback-button'

interface GroupSceneMenuBarProps {
    groupKey: string
    groupTypeIndex: number
}

export function GroupSceneMenuBar(props: GroupSceneMenuBarProps): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <GroupSceneMenuBarInner {...props} /> : null
}

function GroupSceneMenuBarInner({ groupKey, groupTypeIndex }: GroupSceneMenuBarProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const addToNotebookAction = useAddToNotebookAction(RESOURCE_TYPE, {
        notebookSelectButtonProps: {
            resource: { type: NotebookNodeType.Group, attrs: { id: groupKey, groupTypeIndex } },
        },
    })
    const pinActions = useTodayPeoplePinAction()

    const actions: SceneAction[] = [
        // The rail redesign drops adding to notebooks from outside a notebook, as the title button does.
        ...(!todayRailNav ? [addToNotebookAction] : []),
        feedbackSceneAction(RESOURCE_TYPE, FEEDBACK_BUTTON_ID),
        ...pinActions,
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
