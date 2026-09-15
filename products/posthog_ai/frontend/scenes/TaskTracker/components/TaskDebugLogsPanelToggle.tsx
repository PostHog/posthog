import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { ScenePanelActionsSection, ScenePanelDivider } from '~/layout/scenes/SceneLayout'

import { debugLogsLogic } from '../../../logics/debugLogsLogic'

/**
 * Renders nothing, including its divider, unless the current user may control debug logs.
 * Impersonated sessions force debug logs on and do not show the toggle.
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
