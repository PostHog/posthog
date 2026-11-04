import { useActions, useValues } from 'kea'

import { IconBug } from '@posthog/icons'

import type { TodayMenuParts } from '~/layout/today/todayMenuParts'

import { debugLogsLogic } from '../logics/debugLogsLogic'

export function DebugLogsMenuItem({ parts }: { parts: TodayMenuParts }): JSX.Element | null {
    const { canControlDebugLogs, debugLogsEnabled } = useValues(debugLogsLogic)
    const { setDebugLogsEnabled } = useActions(debugLogsLogic)

    if (!canControlDebugLogs) {
        return null
    }
    return (
        <parts.Item onClick={() => setDebugLogsEnabled(!debugLogsEnabled)} dataAttr="run-toggle-debug-logs">
            <IconBug />
            {debugLogsEnabled ? 'Hide debug logs' : 'Show debug logs'}
        </parts.Item>
    )
}
