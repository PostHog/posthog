import { useActions, useValues } from 'kea'

import { IconArchive, IconInfo } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { debugLogsLogic } from '../../../logics/debugLogsLogic'
import type { Task } from '../../../types/taskTypes'

const RESOURCE_TYPE = 'task'

interface TaskRunSceneMenuBarProps {
    task: Task | null
    onArchive: () => void
    /** The title row's run actions, which the page builds. */
    titleActions?: SceneAction[]
}

/** The scene panel's facts and actions. The quill skin keeps them in the title's overflow menu instead. */
export function TaskRunSceneMenuBar(props: TaskRunSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <TaskRunSceneMenuBarInner {...props} /> : null
}

function TaskRunSceneMenuBarInner({ task, onArchive, titleActions = [] }: TaskRunSceneMenuBarProps): JSX.Element {
    const { canControlDebugLogs, debugLogsEnabled } = useValues(debugLogsLogic)
    const { setDebugLogsEnabled } = useActions(debugLogsLogic)

    const actions: SceneAction[] = task
        ? [
              ...titleActions,
              {
                  group: 'file',
                  section: 'delete',
                  id: `${RESOURCE_TYPE}-menubar-archive`,
                  label: 'Archive task',
                  icon: <IconArchive />,
                  destructive: true,
                  onSelect: onArchive,
              },
              ...(canControlDebugLogs
                  ? ([
                        {
                            group: 'staff',
                            type: 'checkbox',
                            // pinned: data-attr values are wire strings
                            id: 'task-toggle-debug-logs',
                            label: 'Show debug logs',
                            checked: debugLogsEnabled,
                            onCheckedChange: setDebugLogsEnabled,
                        },
                    ] satisfies SceneAction[])
                  : []),
              {
                  group: 'metadata',
                  type: 'panel',
                  id: `${RESOURCE_TYPE}-menubar-details`,
                  label: 'Task details',
                  icon: <IconInfo />,
                  render: () => (
                      <>
                          <ScenePanelLabel title="Task ID">
                              <div className="font-mono text-sm">{task.slug}</div>
                          </ScenePanelLabel>
                          <ScenePanelLabel title="Repository">
                              <div className="text-sm">{task.repository}</div>
                          </ScenePanelLabel>
                          <ScenePanelLabel title="Created by">
                              <div className="text-sm">
                                  {task.created_by?.first_name || task.created_by?.email || 'Unknown'}
                              </div>
                          </ScenePanelLabel>
                          <ScenePanelLabel title="Created">
                              <div className="text-sm">{dayjs(task.created_at).format('MMM D, YYYY HH:mm')}</div>
                          </ScenePanelLabel>
                      </>
                  ),
              },
          ]
        : []

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
