import { useActions, useValues } from 'kea'

import { SceneMenuBarCheckboxItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'

import { debugLogsLogic } from '../../../logics/debugLogsLogic'

/**
 * Staff-only menu exposing the debug-logs toggle for the run thread. Renders nothing unless the current
 * user may control debug logs (staff or local dev) — impersonated sessions force debug logs on and have
 * no toggle. The checkmark reflects the persisted (localStorage) preference, on by default.
 */
export function TaskDebugLogsMenu(): JSX.Element | null {
    const { canControlDebugLogs, debugLogsEnabled } = useValues(debugLogsLogic)
    const { setDebugLogsEnabled } = useActions(debugLogsLogic)

    if (!canControlDebugLogs) {
        return null
    }

    return (
        <SceneMenuBarMenu label="Staff only" dataAttr="task-menubar-staff">
            <SceneMenuBarCheckboxItem
                checked={debugLogsEnabled}
                onCheckedChange={(checked) => setDebugLogsEnabled(!!checked)}
                data-attr="task-menubar-show-debug-logs"
            >
                Show debug logs
            </SceneMenuBarCheckboxItem>
        </SceneMenuBarMenu>
    )
}
