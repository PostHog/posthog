import { useValues } from 'kea'

import { IconExternal, IconWarning } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'lib/logic/preflightLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'error-tracking'

const ERROR_TRACKING_DOCS_URL = 'https://posthog.com/docs/error-tracking'

interface ErrorTrackingSceneMenuBarProps {
    onFeedbackClick: () => void
    onSendException: () => void
    onStartExceptionLoop: () => void
}

export function ErrorTrackingSceneMenuBar(props: ErrorTrackingSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ErrorTrackingSceneMenuBarInner {...props} /> : null
}

function ErrorTrackingSceneMenuBarInner({
    onFeedbackClick,
    onSendException,
    onStartExceptionLoop,
}: ErrorTrackingSceneMenuBarProps): JSX.Element {
    const { isDev } = useValues(preflightLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'feedback',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconFeedback />,
            opensFloatingUi: true,
            onSelect: onFeedbackClick,
            pinned: { order: 1, variant: 'secondary' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-documentation`,
            label: 'Documentation',
            icon: <IconExternal />,
            onSelect: () => window.open(ERROR_TRACKING_DOCS_URL, '_blank', 'noopener,noreferrer'),
            pinned: { order: 2, variant: 'secondary' },
        },
        ...(isDev
            ? ([
                  {
                      group: 'staff',
                      id: `${RESOURCE_TYPE}-menubar-send-exception`,
                      label: 'Send an exception',
                      icon: <IconWarning />,
                      onSelect: onSendException,
                  },
                  {
                      group: 'staff',
                      id: `${RESOURCE_TYPE}-menubar-start-exception-loop`,
                      label: 'Start exception loop',
                      icon: <IconWarning />,
                      onSelect: onStartExceptionLoop,
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
