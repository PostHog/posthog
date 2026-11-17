import { IconMessage } from '@posthog/icons'

import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { QuillFeedbackButton } from 'products/customer_analytics/frontend/components/QuillFeedbackButton'

const RESOURCE_TYPE = 'persons'
// pinned: the feedback survey targets this element id
const FEEDBACK_BUTTON_ID = 'customer-analytics-people-list-feedback-button'

export function PersonsSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <PersonsSceneMenuBarInner />
}

function PersonsSceneMenuBarInner(): JSX.Element {
    const fileActions = useSceneFileActions(RESOURCE_TYPE)

    const actions: SceneAction[] = [
        ...fileActions,
        {
            group: 'file',
            section: 'feedback',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconMessage />,
            tooltip: 'Have any questions or feedback?',
            // The survey opens from a click on the element with its id, so the row clicks the title button.
            onSelect: () => document.getElementById(FEEDBACK_BUTTON_ID)?.click(),
            pinned: { order: 1, variant: 'secondary', render: () => <QuillFeedbackButton id={FEEDBACK_BUTTON_ID} /> },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
