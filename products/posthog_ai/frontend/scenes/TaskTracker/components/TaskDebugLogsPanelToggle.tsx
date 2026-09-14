import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { ScenePanelActionsSection, ScenePanelDivider } from '~/layout/scenes/SceneLayout'

import { debugLogsLogic } from '../../../logics/debugLogsLogic'

/**
 * Scene-panel twin of `TaskDebugLogsMenu` — the same debug-logs toggle for users without the scene
 * menu bar. Both surfaces read and write the one persisted preference, so the menu bar and the panel
 * never disagree. Renders nothing (not even its divider) unless the current user may control debug
 * logs: impersonated sessions force debug logs on and have no toggle.
 */
export function TaskDebugLogsPanelToggle(): JSX.Element | null {
    const { canControlDebugLogs, debugLogsEnabled } = useValues(debugLogsLogic)
    const { setDebugLogsEnabled } = useActions(debugLogsLogic)

    if (!canControlDebugLogs) {
        return null
    }

    return (
        <>
            <ScenePanelActionsSection>
                <LemonSwitch
                    data-attr="task-toggle-debug-logs"
                    className="px-2 py-1"
                    checked={debugLogsEnabled}
                    onChange={setDebugLogsEnabled}
                    fullWidth
                    label="Show debug logs"
                />
            </ScenePanelActionsSection>

            <ScenePanelDivider />
        </>
    )
}
