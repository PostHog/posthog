import posthog from 'posthog-js'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFeedback } from 'lib/lemon-ui/icons'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'logs'

const LOGS_FEEDBACK_SURVEY_ID = '019a7d95-3810-0000-34dc-404a58075f17'

interface LogsSceneMenuBarProps {
    hasData: boolean
}

export function LogsSceneMenuBar(props: LogsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <LogsSceneMenuBarInner {...props} /> : null
}

function LogsSceneMenuBarInner({ hasData }: LogsSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = hasData
        ? [
              {
                  group: 'file',
                  section: 'feedback',
                  id: `${RESOURCE_TYPE}-menubar-feedback`,
                  label: 'Feedback',
                  icon: <IconFeedback />,
                  opensFloatingUi: true,
                  onSelect: () => posthog.displaySurvey(LOGS_FEEDBACK_SURVEY_ID),
                  pinned: { order: 1, variant: 'secondary' },
              },
          ]
        : []

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
