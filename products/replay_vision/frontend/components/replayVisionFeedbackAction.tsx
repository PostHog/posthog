import { IconMessage } from '@posthog/icons'

import posthog from 'lib/posthog-typed'

import type { SceneAction, ScenePinned } from '~/layout/scenes/sceneActions/sceneActionModel'

import { ReplayVisionFeedbackButton } from './ReplayVisionFeedbackButton'

/** The Replay vision "Feedback" row for a scene's action list. The captured event opens the feedback survey. */
export function replayVisionFeedbackAction(
    dataAttrKey: string,
    pinned?: Pick<ScenePinned, 'order' | 'variant'>
): SceneAction {
    return {
        group: 'view',
        id: `${dataAttrKey}-menubar-feedback`,
        label: 'Feedback',
        icon: <IconMessage />,
        opensFloatingUi: true,
        tooltip: 'Share feedback on Replay vision',
        onSelect: () => posthog.capture('replay_vision_feedback_clicked'),
        pinned: pinned ? { ...pinned, render: () => <ReplayVisionFeedbackButton /> } : undefined,
    }
}
